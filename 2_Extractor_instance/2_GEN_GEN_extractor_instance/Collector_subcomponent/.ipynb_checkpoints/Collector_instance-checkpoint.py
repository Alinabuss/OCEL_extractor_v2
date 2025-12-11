import json
import os
import re

from openai import AzureOpenAI
from tqdm import tqdm

#from Collector_subcomponent.Modularized_functions.Generative_extractor_setup import generative_extractor_setup
#from Collector_subcomponent.Modularized_functions.OCEL_collection_using_LLM import OCEL_collector_using_LLM


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


def azure_openai_chat_completion(client, model, system_prompt, user_prompt, type="json_object", schema=None):
    if type == "json_schema":
        response_format = {"type": "json_schema", "json_schema": {"name": "schema_name", "schema": schema}}
    else:
        response_format = {"type": "json_object"}
    response = client.chat.completions.create(
        model=model,
        response_format=response_format,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        reasoning_effort='high'
    )
    content = response.choices[0].message.content
    return content


def create_ocel_from_textual_description(client, model, textual_description):
    system_prompt = """
    You are a process mining expert. You will now receive a couple of textual descriptions. 
    Please extract object-centric event logs in the OCEL 2.0 JSON format from these textual desciptions.
    Here is an example on how the OCEL 2.0 standard looks like:
    
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

    You must extract objects, object types, event types, timestamps and event-to-object relationship to create a minimal OCEL 2.0 event log.
    For objects, use names and IDs that you found in the text as object IDs and don't come up with own object IDs.
    If possible and necessary, please also extract object and event attributes as well as object-to-object relationships.
    
    Return ONLY the extracted event log as JSON object in the OCEL 2.0 standard.
    """

    user_prompt = "Extract an OCEL 2.0 event log from the following text:\n\n" + textual_description

    return azure_openai_chat_completion(client, model, system_prompt, user_prompt, type="json_schema", schema=ocel_schema)


def OCEL_collector_using_LLM(report_folder, filename, saving_folder, level, client, model):
    filepath = os.path.join(report_folder, filename)
    with open(filepath, 'r', encoding='utf-8') as file:
        textual_description = file.read()
        event_log = json.loads(create_ocel_from_textual_description(client, model, textual_description))

        # Construct output filename based on the event_id
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
            json.dump(event_log, f, indent=4)


def OCEL_generative_collector_component(dataset_folder, level, api_type, openai_api_key, openai_model, azure_api_key,  azure_endpoint, azure_model):
    if level == 'event':
        report_folder = os.path.join(dataset_folder, "Textual_descriptions/Event_reports/")

    elif level == 'disjunct_event_groups':
        report_folder = os.path.join(dataset_folder, "Textual_descriptions/Disjunct_grouped_reports/")

    elif level == "intersecting_event_groups":
        report_folder = os.path.join(dataset_folder, "Textual_descriptions/Intersecting_grouped_reports/")

    elif level == "Test_setup":
        report_folder = os.path.join(dataset_folder, "Textual_descriptions/Test_reports/")

    saving_folder = os.path.join(dataset_folder, "Extracted_logs/GEN_subsets/")

    os.makedirs(saving_folder, exist_ok=True)
    
    client = AzureOpenAI(azure_endpoint=azure_endpoint, api_key=azure_api_key, api_version='2025-03-01-preview')

    for filename in tqdm(os.listdir(report_folder), desc="Collect information from textual descriptions", unit="file"):
        if filename.endswith(".txt"):  # Process only text files
            OCEL_collector_using_LLM(report_folder, filename,  saving_folder, level, client, azure_model)
