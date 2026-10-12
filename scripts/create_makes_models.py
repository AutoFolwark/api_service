import json

import pandas as pd
import requests
import slugify

from config import settings


def get_json_data_from_api(vehicle_type: str) -> dict:
    url = f"https://api.apicar.store/api/cars/filters?vehicle_type={vehicle_type}&load_all_filters=true"
    headers = {
        "api-key": settings.AUCTION_API_KEY,
    }
    response = requests.get(url, headers=headers)
    return response.json()


def get_json_data():
    with open("cars_filters.json") as f:
        return json.load(f)


VEHICLE_TYPES = [
    "Automobile",
    "Motorcycle",
    "ATV",
    "Watercraft",
    "Jet Sky",
    "Boat",
    "Trailers",
    "Mobile Home",
    "Emergency Equipment",
    "Industrial Equipment",
    "Truck",
    "Bus",
    "Other",
]


GET_VALID_FOR_VEHICLE_TYPE = ["boat", "atv"]


validated_makes = {}


def get_all_makes(vehicle_type: str):
    data = get_json_data_from_api(vehicle_type.lower())
    makes = []
    for make, make_info in data["makes"].items():
        if make_info.get("is_valid"):
            makes.append({make: get_models_for_make(make_info["models"])})
    return makes


def get_models_for_make(models: dict) -> list[str]:
    result = []
    for model, model_info in models.items():
        if model not in GET_VALID_FOR_VEHICLE_TYPE:
            if model_info.get("is_valid") is True:
                result.append(model)
        else:
            result.append(model)
    return result


def build_csvs():
    vt_rows = []
    make_rows = []
    model_rows = []

    vt_id_by_slug = {}
    make_id_by_key = {}

    vt_next_id = 1
    make_next_id = 1
    model_next_id = 1

    for vt_name in VEHICLE_TYPES:
        vt_slug = slugify.slugify(vt_name)
        if vt_slug not in vt_id_by_slug:
            vt_id_by_slug[vt_slug] = vt_next_id
            vt_rows.append({"id": vt_next_id, "name": vt_name, "slug": vt_slug})
            vt_next_id += 1

        vt_id = vt_id_by_slug[vt_slug]
        make_maps = get_all_makes(vt_name) or []

        for make_map in make_maps:
            for make_name, models_list in make_map.items():
                make_slug = slugify.slugify(make_name)
                make_key = f"{vt_id}:{make_slug}"
                if make_key not in make_id_by_key:
                    make_id_by_key[make_key] = make_next_id
                    make_rows.append(
                        {
                            "id": make_next_id,
                            "name": make_name,
                            "slug": make_slug,
                            "vehicle_type_id": vt_id,
                        }
                    )
                    make_next_id += 1

                make_id = make_id_by_key[make_key]
                seen_model_slugs = set()
                for model_name in models_list:
                    model_slug = slugify.slugify(model_name)
                    if model_slug in seen_model_slugs:
                        continue
                    seen_model_slugs.add(model_slug)
                    model_rows.append(
                        {
                            "id": model_next_id,
                            "name": model_name,
                            "slug": model_slug,
                            "make_id": make_id,
                        }
                    )
                    model_next_id += 1

    df_vehicle_type = pd.DataFrame(vt_rows, columns=["id", "name", "slug"])
    df_make = pd.DataFrame(make_rows, columns=["id", "name", "slug", "vehicle_type_id"])
    df_model = pd.DataFrame(model_rows, columns=["id", "name", "slug", "make_id"])

    df_vehicle_type.to_csv("vehicle_type.csv", index=False)
    df_make.to_csv("make.csv", index=False)
    df_model.to_csv("model.csv", index=False)

    return df_vehicle_type, df_make, df_model


if __name__ == "__main__":
    build_csvs()
