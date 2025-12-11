import os
import json
from Refiner_subcomponent.Modularized_functions.OCEL_reader import OCEL_reader
from Refiner_subcomponent.Modularized_functions.OCEL_concatenator import OCEL_concatenator
from Refiner_subcomponent.Modularized_functions.OCEL_generative_refiner import OCEL_generative_refiner

def OCEL_generative_refiner_component(dataset_folder, api_type, openai_api_key, openai_model, azure_api_key,  azure_endpoint, azure_model, azure_api_version):

    extracted_event_log_path = os.path.join(dataset_folder, "Extracted_logs/GEN_subsets/")
    saving_folder = os.path.join(dataset_folder, "Extracted_logs/")

    OCEL_list = OCEL_reader(extracted_event_log_path)
    OCEL_concatenator(OCEL_list, saving_folder)
    OCEL_generative_refiner(dataset_folder, api_type, openai_api_key, openai_model, azure_api_key,  azure_endpoint, azure_model, azure_api_version)


