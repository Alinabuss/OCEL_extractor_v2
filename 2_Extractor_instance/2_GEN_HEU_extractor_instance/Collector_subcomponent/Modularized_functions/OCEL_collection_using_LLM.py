import os
import re
import json

REASONING_EFFORT = 'high'

ocel_schema = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "properties": {
        "objectTypes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": { "type": "string" },
                    "attributes": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": { "type": "string" },
                                "type": { "type": "string" }
                            },
                            "required": ["name", "type"]
                        }
                    }
                },
                "required": ["name", "attributes"]
            }
        },
        "eventTypes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": { "type": "string" },
                    "attributes": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": { "type": "string" },
                                "type": { "type": "string" }
                            },
                            "required": ["name", "type"]
                        }
                    }
                },
                "required": ["name", "attributes"]
            }
        },
        "objects": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": { "type": "string" },
                    "type": { "type": "string" },
                    "relationships": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "objectId": { "type": "string" },
                                "qualifier": { "type": "string" }
                            },
                            "required": ["objectId", "qualifier"]
                        }
                    },
                    "attributes": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": { "type": "string" },
                                "value": { "type": "string" },
                                "time": { "type": "string", "format": "date-time" }
                            },
                            "required": ["name", "value", "time"]
                        }
                    }
                },
                "required": ["id", "type"]
            }
        },
        "events": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": { "type": "string" },
                    "type": { "type": "string" },
                    "time": { "type": "string", "format": "date-time" },
                    "attributes": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": { "type": "string" },
                                "value": { "type": "string" }
                            },
                            "required": ["name", "value"]
                        }
                    },
                    "relationships": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "objectId": { "type": "string" },
                                "qualifier": { "type": "string" }
                            },
                            "required": ["objectId", "qualifier"]
                        }
                    }
                },
                "required": ["id", "type", "time"]
            }
        }
    },
    "required": ["eventTypes", "objectTypes", "events", "objects"]
}



def OCEL_collector_using_LLM(report_folder, filename,  saving_folder, level, client, azure_model):
    filepath = os.path.join(report_folder, filename)
    with open(filepath, 'r', encoding='utf-8', errors='ignore') as file:
        text = file.read()
        
    system_prompt = """
    You are a process mining expert. You will now receive a couple of textual descriptions. 
    Please extract object-centric event logs in the OCEL 2.0 JSON format from these textual descriptions.
    Here is an example of what the OCEL 2.0 standard looks like:

    {
       "objectTypes": [
           {
               "name": "",
               "attributes": [
                   {
                       "name": "",
                       "type": ""
                   }
               ]
           }
       ],
       "eventTypes": [
           {
               "name": "",
               "attributes": [
                   {
                       "name": "",
                       "type": ""
                   },
                   {
                       "name": "",
                       "type": ""
                   }
               ]
           }
       ],
       "objects": [
           {
               "id": "",
               "type": "",
               "attributes": [
                   {
                       "name": "",
                       "time": "",
                       "value": ""
                   }
               ],
               "relationships": [
               {
                       "objectId": "",
                       "qualifier": ""
                   }
               ]
           }
       ],
       "events": [
           {
               "id": ,
               "type": "",
               "time": "YYYY-MM-DDTHH:MM:SSZ",
               "attributes": [
                   {
                       "name": "",
                       "value": ""
                   },
                   {
                       "name": "",
                       "value": ""
                   }
               ],
               "relationships": [
                   {
                       "objectId": "",
                       "qualifier": ""
                   }
               ]
           }
       ]
    }

    Your task is to extract a minimal OCEL 2.0 event log from the provided textual description.
    In particular, you should extract object types (including attributes and types), event types (including attributes and types), 
    object instances (including object type, object attributes, and relationships to other objects), and
    event instances (including event type, event attributes, and relationships to other objects).
    Make sure to adhere to the following guidelines from the OCEL 2.0 specification:
    - Events: 
      Events represent actions or activities that occur within a system or process, such as approving an order, shipping an item, or making a payment.
      Each event is unique and corresponds to a specific action or observation at a specific point in time. 
      Events are atomic (i.e., do not take time), have a timestamp, and may have additional attributes. 
      Events are typed.
    - Event Types:
      Events are categorized into different types based on their nature or function. 
      For example, a procurement process might have event types such as Order Created, Order Approved, or Invoice Sent. 
      Each type of event represents a specific kind of action that can take place in the process. 
      Each event is of exactly one type.
    - Objects:
      Objects represent the entities that are involved in events. 
      These might be physical items like products in a supply chain, machines, workers, or abstract/information entities like orders, invoices, or contracts in a procurement process. 
      Objects have unique identifiers and attributes with values, e.g., prices.
      Attribute values may change over time.
    - Object Types:
      Each object is of one type. 
      The object is an instantiation of its type.
      Object types might include categories like Product, Order, Invoice, or Supplier.
    - Event-to-Object Relationships: 
      Events are associated with objects. 
      This relationship describes that an object affects an event or that an event affects an object. 
      Events can be related to multiple objects. 
      Furthermore, these relationships can be qualified differently, describing the role an object plays in the occurrence of this specific event. 
      Consider, for example, a meeting event involving multiple participant objects. 
      Using a qualifier, it is possible to distinguish between regular participants and the organizer of the meeting.
    - Object-to-Object Relationships: 
      Objects can also be related to other objects outside the context of an event. 
      For example, an employee may be part of an organizational unit. 
      In addition to the mere existence of a relation, this relationship can also be qualified (e.g., part-of, reports-to, or belongs-to).

    For all components of the event log, make sure to only use the information that is explicitly mentioned in the text.
    Also, do not model relationships as event attributes or object attributes, but as event-to-object or object-to-object relationships.

    Return ONLY the extracted event log as a JSON object in the OCEL 2.0 standard.
    """

    user_prompt = "Extract an OCEL 2.0 event log from the following text:\n\n" + text

    response = client.chat.completions.create(
        model=azure_model,
        response_format={"type": "json_schema", "json_schema": {"name": "schema_name", "schema": ocel_schema}},
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        reasoning_effort=REASONING_EFFORT
    )

    ocel_log = json.loads(response.choices[0].message.content)

    if level == 'event':
        event_id = re.search(r'_event_(.+?)_textual_report', filepath).group(1)
    elif level == 'disjunct_event_groups':
        event_id = re.search(r'Daily_report_(.+?).txt', filepath).group(1)
    elif level == 'intersecting_event_groups':
        event_id = re.search(r'Object_report_(.+?).txt', filepath).group(1)
    elif level == 'Test_setup':
        event_id = re.search(r'report_(.+?).txt', filepath).group(1)

    json_output_filename = f"OCEL_{event_id}.json"

    json_output_filepath = os.path.join(saving_folder, json_output_filename)

    # Write the OCEL2.0 log to a JSON file
    with open(json_output_filepath, "w") as f:
        json.dump(ocel_log, f, indent=4)
