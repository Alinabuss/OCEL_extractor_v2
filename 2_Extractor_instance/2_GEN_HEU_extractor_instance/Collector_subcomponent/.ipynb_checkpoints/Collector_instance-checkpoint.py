import os
from tqdm import tqdm
import openai
from Collector_subcomponent.Modularized_functions.OCEL_collection_using_LLM import OCEL_collector_using_LLM

def OCEL_generative_collector_component(dataset_folder, level, api_type, openai_api_key, openai_model, azure_api_key,  azure_endpoint, azure_model, azure_api_version):
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

    if api_type == "openai":
        client = openai.OpenAI(api_key=openai_api_key)
    elif api_type == "azure":
        client = openai.AzureOpenAI(
            api_key=azure_api_key,
            api_version=azure_api_version,
            azure_endpoint=azure_endpoint
        )

    for filename in tqdm(os.listdir(report_folder), desc="Collect information from textual descriptions", unit="file"):
        if filename.endswith(".txt"):  # Process only text files
            OCEL_collector_using_LLM(report_folder, filename,  saving_folder, level, client, azure_model)


