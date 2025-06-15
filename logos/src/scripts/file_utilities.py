"""
This module provides easy to use methods to export and import the database of Logos.
"""
import json
from pprint import pprint

import requests


def export_to_json(logos_base_url: str, logos_key: str, file_path: str, verify: bool = True):
    """
    Exports a logos database to a json file.
    :param logos_base_url: Base URL under which logos is running without final slash, e.g. "http://logos.ase.cit.tum.de:8080"
    :param logos_key: A valid logos root key
    :param file_path: Path to file to export to
    :param verify: Verify SSL-Certificate of connection
    :return: None
    """
    headers = {
        "Content-Type": "application/json",
        "logos_key": f"{logos_key}",
    }

    data = {
        "logos_key": f"{logos_key}",
    }
    response = requests.post(f"{logos_base_url}/logosdb/export", json=data, headers=headers, verify=verify)
    if response.status_code == 200:
        print("Database successfully exported")
    else:
        pprint(response.json())
        return

    with open(file_path, "w") as f:
        json.dump(response.json()[0]["result"], f, ensure_ascii=False, indent=4)


def import_from_json(logos_base_url: str, logos_key: str, file_path: str, verify: bool = True):
    """
    Imports a logos database from a json file.
    :param logos_base_url: Base URL under which logos is running without final slash, e.g. "http://logos.ase.cit.tum.de:8080"
    :param logos_key: A valid logos root key
    :param file_path: Path to file to import from
    :param verify: Verify SSL-Certificate of connection
    :return: None
    """
    headers = {
        "Content-Type": "application/json",
        "logos_key": f"{logos_key}",
    }
    with open(file_path, "r") as json_file:
        json_data = json.load(json_file)

    data = {
        "logos_key": f"{logos_key}",
        "json_data": json_data

    }

    response = requests.post(f"{logos_base_url}/logosdb/import", json=data, headers=headers, verify=verify)
    if response.status_code == 200:
        print("Database successfully imported")
    else:
        pprint(response.json())
