import json
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
import openai
import os
import tqdm
import datetime


REASONING_EFFORT = 'high'

def azure_openai_chat_completion(client, azure_model, system_prompt, user_prompt, dictionary, type="json_object", schema=None):
    if type == "json_schema":
        response_format = {"type": "json_schema", "json_schema": {"name": "schema_name", "schema": schema}}
    else:
        response_format = {"type": "json_object"}
    response = client.chat.completions.create(
        model=azure_model,
        response_format=response_format,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt + json.dumps(dictionary)}
        ],
        reasoning_effort=REASONING_EFFORT
    )
    content = response.choices[0].message.content
    return content


def get_ocel_component_counts(event_log, component_name):
    component = event_log.get(component_name, {})
    names = []
    for component_type in component:
        names.append(component_type.get('name', ''))
    return Counter(names)


attribute_mapping_schema = {
    "type": "object",
    "properties": {},
    "additionalProperties": {
        "properties": {
            "name": {"type": "string"},
            "type": {"type": "string", "enum": ["string", "float", "integer", "boolean", "time"]}
        },
        "required": ["name", "type"],
        "additionalProperties": False
    }
}


def refine_object_attributes(client, azure_model, object_type, object_attributes_dict):
    system_prompt = """
    You are a process mining expert. Your task is to refine object attributes in an object-centric event log.
    Next to the object type, you will receive a list of possible object attributes and their respective type.
    Your goal is to refine the object attributes by merging similar ones and ensuring that each resulting attribute is distinct, meaningful and specific.
    If an attribute is not relevant for the object type, you can remove it.
    Please respond with a JSON object whose keys are the original attribute names and the values are their refined names and types.
    The values in the JSON object should be single dictionaries with the keys 'name' and 'type'.
    Return nothing except the JSON object.
    """

    user_prompt = "Refine the attributes of the object type '{}': \n\n".format(object_type)

    return azure_openai_chat_completion(client, azure_model, system_prompt, user_prompt, object_attributes_dict, type="json_schema", schema=attribute_mapping_schema)


def refine_object_instance_ids(client, azure_model, object_type, object_instances):
    system_prompt = """
    You are a process mining expert. Your task is to refine object instance IDs in an object-centric event log.
    The object type is provided as a string and the object instance IDs are provided as a list of strings.
    Your goal is to refine the object instance IDs by merging similar ones and ensuring that each resulting name is distinct, meaningful and specific.
    Please respond with a JSON object whose keys are the original object instance IDs and the values are their refined IDs.
    Ensure that each object instance in the original list is present in the response, even if it is not refined.
    Do not use regular expressions in your response and do not introduce abbreviations if they are not present in the original IDs.
    Return nothing except the JSON object.
    """

    user_prompt = "Refine the object instance IDs of the object type '{}': \n\n".format(object_type)

    return azure_openai_chat_completion(client, azure_model, system_prompt, user_prompt, object_instances)


def refine_event_attributes(client, azure_model, event_type, event_attributes_dict):
    system_prompt = """
    You are a process mining expert. Your task is to refine event attributes in an object-centric event log.
    Next to the event type, you will receive a list of possible event attributes and their respective type.
    Your goal is to refine the event attributes by merging similar ones and ensuring that each resulting attribute is distinct, meaningful and specific.
    If an attribute is not relevant for the event type, you can remove it.
    Please respond with a JSON object whose keys are the original attribute names and the values are their refined names and types.
    The values in the JSON object should be single dictionaries with the keys 'name' and 'type'.
    Return nothing except the JSON object.
    """

    user_prompt = "Refine the attributes of the event type '{}': \n\n".format(event_type)

    return azure_openai_chat_completion(client, azure_model, system_prompt, user_prompt, event_attributes_dict, type="json_schema", schema=attribute_mapping_schema)


def process_object_type_instances(client, azure_model, object_type, data):
    print(f"Refining object instances for object type: {object_type}")
    current_object_instance_ids = [obj.get('id') for obj in data.get('objects', []) if obj.get('type') == object_type]
    print(f"Current object instance IDs: {current_object_instance_ids}")
    return object_type, json.loads(refine_object_instance_ids(client, azure_model, object_type, current_object_instance_ids))


def process_object_type(client, azure_model, obj):
    object_type = obj['name']
    print(f"Refining attributes for object type: {object_type}")
    print(f"Attributes: {obj.get('attributes', {})}")
    if len(obj.get('attributes', {})):
        refined_attributes = json.loads(refine_object_attributes(client, azure_model, object_type, obj.get('attributes', {})))
        return object_type, {k: v for k, v in refined_attributes.items() if v.get('name') not in (None, '')}
    else:
        return object_type, obj.get('attributes', {})


def process_event_type(client, azure_model, event):
    event_type = event['name']
    print(f"Refining attributes for event type: {event_type}")
    print(f"Attributes: {event.get('attributes', {})}")
    if len(event.get('attributes', {})) > 0:
        refined_attributes = json.loads(refine_event_attributes(client, azure_model, event_type, event.get('attributes', {})))
        return event_type, {k: v for k, v in refined_attributes.items() if v.get('name') not in (None, '')}
    else:
        return event_type, event.get('attributes', {})


def OCEL_generative_refiner(dataset_folder, api_type, openai_api_key, openai_model, azure_api_key, azure_endpoint, azure_model, azure_api_version):
    saving_folder = os.path.join(dataset_folder, "Extracted_logs/")
    os.makedirs(saving_folder, exist_ok=True)
    concatenated_log_filepath = os.path.join(saving_folder, "concatenated_event_log.json")
    final_log_filepath = os.path.join(saving_folder, "final_event_log.json")

    if api_type == "openai":
            client = openai.OpenAI(api_key=openai_api_key)
            
    elif api_type == "azure":
            client = openai.AzureOpenAI(
                api_key=azure_api_key,
                api_version=azure_api_version,
                azure_endpoint=azure_endpoint,
            )
    
    with open(concatenated_log_filepath, 'r') as file:
        data = json.load(file)
        object_types = get_ocel_component_counts(data, 'objectTypes')
        event_types = get_ocel_component_counts(data, 'eventTypes')
        object_instances = data.get('objects', [])

    # Refine object types
    print("refining Object types")   
    refine_object_types_system_prompt = """
    You are a process mining expert. Your task is to refine object types in an object-centric event log.
    The object types are provided in the form of a dictionary where the keys are the object types and the values are their respective counts.
    Your goal is to refine the object types by merging similar ones and ensuring that each resulting object type is distinct, meaningful and specific.
    Please respond with a JSON object whose keys are the original object types and the values are the refined object types.
    Ensure that each object type in the original dictionary is present in the response, even if it is not refined.
    Return nothing except the JSON object.
    """

    refine_object_types_user_prompt = "Refine these object types: \n\n"
    mapping_object_types = json.loads(azure_openai_chat_completion(client, azure_model, refine_object_types_system_prompt, refine_object_types_user_prompt, object_types))

    object_instances_to_remove = []

    for obj in data['objects']:
        obj_type = obj.get('type')
        if obj_type in mapping_object_types:
            obj['type'] = mapping_object_types[obj_type]
        else:
            object_instances_to_remove.append(obj)

    for obj in object_instances_to_remove:
        data['objects'].remove(obj)
    
    refined_data = {}
    refined_data['objectTypes'] = []

    for object_type in data['objectTypes']:
        original_name = object_type['name']

        if original_name in mapping_object_types:
            new_object_type = {
                'name': mapping_object_types[original_name],
                'attributes': object_type.get('attributes', {})
            }

            if new_object_type['name'] not in [obj['name'] for obj in refined_data['objectTypes']]:
                refined_data['objectTypes'].append(new_object_type)
            else:
                for existing_object in refined_data['objectTypes']:
                    if existing_object['name'] == new_object_type['name']:
                        for attr in new_object_type['attributes']:
                            if attr not in existing_object['attributes']:
                                existing_object['attributes'].append(attr)
                        break
    
    # Refine object instance IDs
    print("refining Object instance IDs")
    
    refined_object_types = list(set(mapping_object_types.values()))
    mapping_object_instances = {}

    with ThreadPoolExecutor() as executor:
        futures = [executor.submit(process_object_type_instances, client, azure_model, object_type, data) for object_type in refined_object_types]
        for future in tqdm.tqdm(as_completed(futures), total=len(futures), desc="Refining object instance IDs"):
            object_type, mapping_object_instance_ids = future.result()
            mapping_object_instances[object_type] = mapping_object_instance_ids

    object_instances_to_remove = []

    for obj in data['objects']:
        old_object_id = obj.get('id')
        old_object_type = obj.get('type')
        if old_object_type in mapping_object_instances and old_object_id in mapping_object_instances[old_object_type]:
            new_object_id = mapping_object_instances[old_object_type][old_object_id]
            obj['id'] = new_object_id
            for event in data.get('events', []):
                relationships = event.get('relationships', [])
                for relationship in relationships:
                    if relationship.get('objectId') == old_object_id:
                        relationship['objectId'] = new_object_id
            for object in data.get('objects', []):
                relationships = object.get('relationships', [])
                for relationship in relationships:
                    if relationship.get('objectId') == old_object_id:
                        relationship['objectId'] = new_object_id
                    
        else:
            object_instances_to_remove.append(obj)

    for obj in object_instances_to_remove:
        data['objects'].remove(obj)
    
    # refine eventTypes
    print("refining Event types")
    
    refine_event_types_system_prompt = """
    You are a process mining expert. Your task is to refine event names in an object-centric event log.
    The event names are provided in the form of a dictionary where the keys are the event names and the values are their respective counts.
    Your goal is to refine the event names by merging similar ones and ensuring that each resulting event type is distinct, meaningful and specific.
    Event types typically start with a verb, are in the present tense, and can contain the object of the action.
    Please respond with a JSON object whose keys are the original event names and the values are the refined event types.
    Ensure that each event name in the original dictionary is present in the response, even if it is not refined.
    Return nothing except the JSON object.
    """

    refine_event_types_user_prompt = "Refine these event types: \n\n"

    mapping_event_types = json.loads(azure_openai_chat_completion(client, azure_model, refine_event_types_system_prompt, refine_event_types_user_prompt, event_types))
    
    refined_data['eventTypes'] = []

    for event_type in data['eventTypes']:
        original_name = event_type['name']

        if original_name in mapping_event_types:
            new_event_type = {
                'name': mapping_event_types[original_name],
                'attributes': event_type.get('attributes', {})
            }

            if new_event_type['name'] not in [event['name'] for event in refined_data['eventTypes']]:
                refined_data['eventTypes'].append(new_event_type)
            else:
                for existing_event in refined_data['eventTypes']:
                    if existing_event['name'] == new_event_type['name']:
                        for attr in new_event_type['attributes']:
                            if attr not in existing_event['attributes']:
                                existing_event['attributes'].append(attr)
                        break
                        
    # refine objectAttributes
    mapping_object_attributes = {}

    with ThreadPoolExecutor() as executor:
        futures = [executor.submit(process_object_type, client, azure_model, obj) for obj in refined_data['objectTypes']]
        for future in tqdm.tqdm(as_completed(futures), total=len(futures), desc="Refining object attributes"):
            object_type, refined_attrs = future.result()
            mapping_object_attributes[object_type] = refined_attrs

    # refine eventAttributes
    mapping_event_attributes = {}

    with ThreadPoolExecutor() as executor:
        futures = [executor.submit(process_event_type, client, azure_model, event) for event in refined_data['eventTypes']]
        for future in tqdm.tqdm(as_completed(futures), total=len(futures), desc="Refining event attributes"):
            event_type, refined_attrs = future.result()
            mapping_event_attributes[event_type] = refined_attrs


    # now it's time to apply the changes to the refined data
    for object_type in refined_data['objectTypes']:
        object_type_name = object_type['name']
        object_type_attributes = object_type.get('attributes', {})
        object_type['attributes'] = []
        if object_type_name in mapping_object_attributes:
            if len(mapping_object_attributes[object_type_name]) > 0:
                for old_object_type, mapping in mapping_object_attributes[object_type_name].items():
                    new_attribute = {
                        'name': mapping['name'],
                        'type': mapping['type']
                    }
                    if new_attribute not in object_type['attributes']:
                        object_type['attributes'].append(new_attribute)


    # do the same for the event types
    for event_type in refined_data['eventTypes']:
        event_type_name = event_type['name']
        event_type_attributes = event_type.get('attributes', {})
        event_type['attributes'] = []
        if event_type_name in mapping_event_attributes:
            if len(mapping_event_attributes[event_type_name]) > 0:
                for old_event_type, mapping in mapping_event_attributes[event_type_name].items():
                    new_attribute = {
                        'name': mapping['name'],
                        'type': mapping['type']
                    }
                    if new_attribute not in event_type['attributes']:
                        event_type['attributes'].append(new_attribute)
                        
                        
    # refine objects
    refined_data['objects'] = []

    for object in data['objects']:
        attributes = object.get('attributes', {})
        # check if the attributes are in the mapping
        if object['type'] in mapping_object_attributes:
            # if yes, replace the attributes with the refined attributes
            mappings = mapping_object_attributes[object['type']]
            new_attributes = []
            for element in attributes:
                if element['name'] in mappings:
                    # replace the attribute name and type
                    new_attribute = {
                        'name': mappings[element['name']].get('name'),
                        'type': mappings[element['name']].get('type'),
                        'value': element['value']
                    }
                    # only add the new attribute if there is not already an attribute with the same name and type
                    if new_attribute['name'] not in [attr['name'] for attr in new_attributes] or \
                        new_attribute['type'] not in [attr['type'] for attr in new_attributes]:
                        new_attributes.append(new_attribute)
        else:
            # if the attribute is not in the mapping, remove it
            new_attributes = []
        
        # now check if the object is already in the refined data
        if object['id'] not in [obj['id'] for obj in refined_data['objects']]:
            # if not, add it to the refined data
            refined_data['objects'].append({
                'id': object['id'],
                'type': object['type'],
                'attributes': new_attributes,
                'relationships': []
            })
        else:
            # if yes, append the attributes to the existing object only if they are not already present with same name and type
            # and only append the attributes if the type of the new object is the same as the existing object
            # this is to avoid adding attributes of other object types to the existing object
            for existing_object in refined_data['objects']:
                if existing_object['id'] == object['id'] and existing_object['type'] == object['type']:
                    for new_attribute in new_attributes:
                        if new_attribute['name'] not in [attr['name'] for attr in existing_object['attributes']] or \
                            new_attribute['type'] not in [attr['type'] for attr in existing_object['attributes']]:
                            existing_object['attributes'].append(new_attribute)
                    break
                        
                        
    # refine events
    refined_data['events'] = []

    for event in data['events']:
        # check if the event type is in the event type mapping
        if event['type'] in mapping_event_types:
            # if yes, replace the type with the refined type
            event['type'] = mapping_event_types[event['type']]
            attributes = event.get('attributes', {})
            # check if the time is a valid ISO 8601 date
            try:
                datetime.datetime.fromisoformat(event['time'])
            except (ValueError, TypeError) as e:
                print(f"Event '{event}' has an invalid date format, skipping.")
                continue

            # check if the attributes are in the mapping
            if event['type'] in mapping_event_attributes:
                # if yes, replace the attributes with the refined attributes
                mappings = mapping_event_attributes[event['type']]
                new_attributes = []
                for element in attributes:
                    if element['name'] in mappings:
                        # replace the attribute name and type
                        new_attribute = {
                            'name': mappings[element['name']].get('name'),
                            'type': mappings[element['name']].get('type'),
                            'value': element['value']
                        }
                        # only add the new attribute if there is not already an attribute with the same name and type
                        if new_attribute['name'] not in [attr['name'] for attr in new_attributes] or \
                            new_attribute['type'] not in [attr['type'] for attr in new_attributes]:
                            new_attributes.append(new_attribute)
            else:
                # if the attribute is not in the mapping, remove it
                new_attributes = []

            # now check if the event is already in the refined data
            if event['id'] not in [ev['id'] for ev in refined_data['events']] and not any(
                ev['time'] == event['time'] and ev['type'] == event['type'] for ev in refined_data['events']
            ):
                # if not, add it to the refined data
                refined_data['events'].append({
                    'id': event['id'],
                    'type': event['type'],
                    'attributes': new_attributes,
                    'time': event.get('time', ''),
                    'objectIds': event.get('objectIds', []),
                    'relationships': []
                })
            else:
                # if yes, append the attributes to the existing event only if they are not already present with same name and type
                # and only append the attributes if the type of the new event is the same as the existing event
                # this is to avoid adding attributes of other event types to the existing event
                for existing_event in refined_data['events']:
                    if (existing_event['id'] == event['id'] or existing_event['time'] == event['time']) and existing_event['type'] == event['type']:
                        for new_attribute in new_attributes:
                            if new_attribute['name'] not in [attr['name'] for attr in existing_event['attributes']] or \
                                new_attribute['type'] not in [attr['type'] for attr in existing_event['attributes']]:
                                existing_event['attributes'].append(new_attribute)
                                


    # now iterate through the objects in the initial data and add their relationships to the refined data
    # a relationship is a dict with the keys 'objectId' and 'qualifier'
    # only add the relationship if the object type is in the mapping, the object is in the refined data, the relationship is not already present and the related object is also in the refined data
    # also make sure that the relationship is not a self-relationship (i.e. the objectId is not the same as the id of the object)

    for object in data['objects']:
        # check if the object type is in the object types of the refined data
        if object['type'] in [obj['name'] for obj in refined_data['objectTypes']]:
            # now check if the object is already in the refined data
            for refined_object in refined_data['objects']:
                if refined_object['id'] == object['id'] and refined_object['type'] == object['type']:
                    # now iterate through the relationships of the object
                    for relationship in object.get('relationships', []):
                        related_object_id = relationship.get('objectId')
                        qualifier = relationship.get('qualifier')
                        # check if the related object is in the refined data and not a self-relationship
                        if related_object_id != object['id'] and related_object_id in [obj['id'] for obj in refined_data['objects']]:
                            # check if the relationship is already present
                            if not any(rel['objectId'] == related_object_id and rel['qualifier'] == qualifier for rel in refined_object.get('relationships', [])):
                                # add the relationship to the refined object
                                if 'relationships' not in refined_object:
                                    refined_object['relationships'] = []
                                refined_object['relationships'].append({
                                    'objectId': related_object_id,
                                    'qualifier': qualifier
                                })
                                

    
    # now do the same for the events
    for event in data['events']:
        # check if the event type is in the event types of the refined data
        if event['type'] in [ev['name'] for ev in refined_data['eventTypes']]:
            # now check if the event is already in the refined data
            for refined_event in refined_data['events']:
                if (refined_event['id'] == event['id'] or refined_event['time'] == event['time']) and refined_event['type'] == event['type']:
                    # now iterate through the relationships of the event
                    for relationship in event.get('relationships', []):
                        related_object_id = relationship.get('objectId')
                        qualifier = relationship.get('qualifier')
                        # check if the related object is in the refined data and not a self-relationship
                        if related_object_id in [obj['id'] for obj in refined_data['objects']]:
                            # check if the relationship is already present
                            if not any(rel['objectId'] == related_object_id and rel['qualifier'] == qualifier for rel in refined_event.get('relationships', [])):
                                # add the relationship to the refined event
                                if 'relationships' not in refined_event:
                                    refined_event['relationships'] = []
                                refined_event['relationships'].append({
                                    'objectId': related_object_id,
                                    'qualifier': qualifier
                                })


    # loop over all events, if there are no events of a certain type, remove that event type
    event_types_to_remove = []
    for event_type in refined_data['eventTypes']:
        matching_events = [event for event in refined_data['events'] if event['type'] == event_type['name']]
        if len(matching_events) == 0:
            event_types_to_remove.append(event_type)
            print(f"Removed event type '{event_type['name']}' because it has no events.")

    for event_type in event_types_to_remove:
        refined_data['eventTypes'].remove(event_type)

    # loop over all objects, if there are no objects of a certain type, remove that object type
    object_types_to_remove = []
    for object_type in refined_data['objectTypes']:
        matching_objects = [obj for obj in refined_data['objects'] if obj['type'] == object_type['name']]
        if len(matching_objects) == 0:
            object_types_to_remove.append(object_type)
            print(f"Removed object type '{object_type['name']}' because it has no objects.")

    for object_type in object_types_to_remove:
        refined_data['objectTypes'].remove(object_type)

    # loop over all event types and event attributes in the refined data
    # for each event attribute, check if there is at least one event with a non-null value for that attribute
    # if not, remove the attribute from the event type
    for event_type in refined_data['eventTypes']:
        attributes_to_remove = []
        for attribute in event_type['attributes']:
            # Check if there is at least one event with a non-null value for this attribute of the event type
            matching_events = [event for event in refined_data['events'] if event['type'] == event_type['name']]
            matching_events = [event for event in matching_events if any(attr['name'] == attribute['name'] and attr['value'] is not None for attr in event['attributes'])]
            if not len(matching_events) > 0:
                attributes_to_remove.append(attribute)
                print(f"Removed attribute '{attribute['name']}' from event type '{event_type['name']}' because it has no non-null values.")
        for attribute in attributes_to_remove:
            event_type['attributes'].remove(attribute)

    # do the same for object types and object attributes
    for object_type in refined_data['objectTypes']:
        attributes_to_remove = []
        for attribute in object_type['attributes']:
            # Check if there is at least one object with a non-null value for this attribute of the object type
            matching_objects = [obj for obj in refined_data['objects'] if obj['type'] == object_type['name']]
            matching_objects = [obj for obj in matching_objects if any(attr['name'] == attribute['name'] and attr['value'] is not None for attr in obj['attributes'])]
            if not len(matching_objects) > 0:
                attributes_to_remove.append(attribute)
                print(f"Removed attribute '{attribute['name']}' from object type '{object_type['name']}' because it has no non-null values.")
        for attribute in attributes_to_remove:
            object_type['attributes'].remove(attribute)


    with open(final_log_filepath, 'w') as refined_file:
        json.dump(refined_data, refined_file, indent=4)

    print("Total Event Types: " + str(len(refined_data.get('eventTypes', []))))
    print("Total Events: " + str(len(refined_data.get('events', []))))
    print("Total Object Types: " + str(len(refined_data.get('objectTypes', []))))
    print("Total Objects: " + str(len(refined_data.get('objects', []))))