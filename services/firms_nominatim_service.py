import requests
import logging
import folium
import geopandas as gpd
import pandas as pd

from datetime import date
from functools import lru_cache
from io import StringIO
from streamlit_folium import st_folium

from models.firms_nominatim_models import nominatim_country_codes


FIRMS_API_URL = "https://firms.modaps.eosdis.nasa.gov"


def get_account_status(map_key: str):  # = FIRMS_MAP_KEY
    status_url = f"{FIRMS_API_URL}/mapserver/mapkey_status/?MAP_KEY={map_key}"

    try:
        df = pd.read_json(status_url, typ="series")
    except ValueError:
        # possible error, wrong MAP_KEY value, check for extra quotes, missing letters
        print("There is an issue with the query. \nTry in your browser: %s" % status_url)

    return df


def get_current_transaction_count(map_key: str):  # = FIRMS_MAP_KEY
    status_url = f"{FIRMS_API_URL}/mapserver/mapkey_status/?MAP_KEY={map_key}"
    count = 0

    try:
        df = pd.read_json(status_url, typ="series")
        count = df["current_transactions"]

    except ValueError:
        print("Error in our call.")

    return count


def create_firms_csv_urls(
    firms_key: str  # = FIRMS_MAP_KEY
) -> tuple[str, str, str]:

    # Check if the key is provided and not empty
    if not firms_key:
        raise ValueError("FIRMS key is required and cannot be empty.")

    # Check if the key is a valid hexadecimal string and has a standard length (e.g., 32 characters)
    if not all(c in "0123456789abcdef" for c in firms_key.lower()) or len(firms_key) != 32:
        raise ValueError("Invalid FIRMS key. Key should be a 32-character hexadecimal string.")

    firms_csv_data_urls = (
        f"{FIRMS_API_URL}/api/area/csv/{firms_key}/MODIS_NRT/world/9",
        f"{FIRMS_API_URL}/api/area/csv/{firms_key}/VIIRS_NOAA20_NRT/world/9",
        f"{FIRMS_API_URL}/api/area/csv/{firms_key}/VIIRS_SNPP_NRT/world/9",
    )

    return firms_csv_data_urls


def read_firm_csv(
    url: str,
) -> pd.DataFrame:

    try:
        content = fetch_firms_csv_content(url)
        return process_csv_data(content)

    except Exception as e:
        logging.error(f"Error reading and processing CSV from URL '{url}': {e}")
        raise ValueError(f"Failed to read and process CSV from '{url}'") from e


def fetch_firms_csv_content(url: str) -> StringIO:

    try:
        response = requests.get(url)
        response.raise_for_status()
        return StringIO(response.content.decode("utf-8"))

    except (requests.HTTPError, requests.ConnectionError, OSError) as e:
        logging.error(f"Error fetching CSV content from URL '{url}': {e}")
        raise ValueError(f"Failed to fetch content from '{url}'") from e


def process_csv_data(csv_content: StringIO) -> pd.DataFrame:

    data = pd.read_csv(csv_content, dtype={"acq_date": str, "acq_time": str})

    try:
        # Data processing logic...
        data["high_confidence"] = False  # Initialize the column with False

        # Check for required columns
        required_columns = ["confidence", "acq_date", "acq_time", "satellite"]
        missing_columns = [col for col in required_columns if col not in data.columns]
        if missing_columns:
            raise ValueError(f"Missing required columns in the CSV data: {missing_columns}")

        # Mark the rows that meet the confidence criteria
        if pd.api.types.is_numeric_dtype(data["confidence"]):
            data.loc[data["confidence"] >= 70, "high_confidence"] = True
            data.rename(
                columns={
                    "brightness": "brightness_a",
                    "bright_t31": "brightness_b",
                },
                inplace=True,
            )
        elif pd.api.types.is_string_dtype(data["confidence"]):
            data.loc[data["confidence"].isin(["nominal", "high"]), "high_confidence"] = True
            data.rename(
                columns={
                    "bright_ti4": "brightness_a",
                    "bright_ti5": "brightness_b",
                },
                inplace=True,
            )

        # Process acquisition datetime
        data["acq_time"] = data["acq_time"].str.pad(width=4, side="left", fillchar="0")
        data["acq_datetime"] = pd.to_datetime(
            data["acq_date"] + " " + data["acq_time"].astype(str).str.zfill(4),
            format="%Y-%m-%d %H%M%S",
            errors="coerce"
        )

        # Check for datetime conversion errors
        if data["acq_datetime"].isnull().any():
            raise ValueError("Error converting acquisition datetime")

        # Calculate "days_ago"
        if data["acq_date"].max() == pd.Timestamp(date.today()):
            data["days_ago"] = (
                data["acq_date"].rank(method="dense", ascending=False).astype(int) - 1
            )
        else:
            data["days_ago"] = (
                data["acq_date"].rank(method="dense", ascending=False).astype(int)
            )

        # Type conversions
        data["satellite"] = data["satellite"].astype(str)
        data["confidence"] = data["confidence"].astype(str)

        return data

    except Exception as e:
        logging.error(f"Error processing CSV data: {e}")
        raise ValueError(f"Data processing error: {e}") from e


@lru_cache()
def convert_firms_urls_to_combined_gdf(
    firms_urls: tuple[str, str, str]
) -> gpd.GeoDataFrame:

    # Validate input
    if not isinstance(firms_urls, tuple) or len(firms_urls) != 3:
        raise ValueError("firms_urls must be a tuple of three strings")

    # Initialize an empty DataFrame
    single_df = pd.DataFrame()
    combined_df_list = [single_df]

    for url in firms_urls:
        df = read_firm_csv(url)  # Assuming read_firm_csv is a defined function
        combined_df_list.append(df)

    combined_df = pd.concat(combined_df_list, ignore_index=True)

    # Check for required columns
    required_columns = ['high_confidence', 'latitude', 'longitude', 'acq_datetime', 'confidence', 'version']
    missing_columns = [col for col in required_columns if col not in combined_df.columns]
    if missing_columns:
        raise ValueError(f"Missing required columns in the data: {missing_columns}")

    # Assuming there's a column named 'high_confidence' in the DataFrame
    combined_df = combined_df[combined_df["high_confidence"]].copy()

    # Drop duplicates
    unique_columns = ["latitude", "longitude", "acq_datetime", "confidence", "version"]
    combined_df_export = combined_df.drop_duplicates(subset=unique_columns, keep="last").copy()

    # Sort and drop unnecessary columns
    combined_df_export.sort_values(["acq_datetime"], inplace=True)
    drop_columns = ['scan', 'track', 'acq_date', 'acq_time', 'brightness_a', 'brightness_b', 'daynight']
    combined_df_export.drop(drop_columns, axis=1, inplace=True)

    # Convert to GeoDataFrame
    gdf = gpd.GeoDataFrame(
        combined_df_export,
        geometry=gpd.points_from_xy(combined_df_export.longitude, combined_df_export.latitude),
        crs="EPSG:4326",
    )

    # Format datetime
    gdf["acq_datetime"] = gdf["acq_datetime"].dt.strftime("%Y-%m-%d_%H:%M:%S")

    return gdf


def create_nominatim_search_url(
    country_code: nominatim_country_codes = "BJ"
) -> str:
    """
    Function to fetch OSM Search URL using Nominatim Search API

    Parameters
    ----------
        country_code: str - country code of the country to be queried

    Returns
        search_url: str - url of the nominatim query result
    -------
    """

    NOMINATIM_SEARCH_ENDPOINT = "https://nominatim.openstreetmap.org/search"

    params = {
        "namedetails": 1,
        "polygon_geojson": 1,
        "hierarchy": 1,
        "addresstype": "country",
    }

    params_query = "&".join(f"{param_name}={param_value}" for param_name, param_value in params.items())
    nominatim_search_url = (
        f"{NOMINATIM_SEARCH_ENDPOINT}?q={country_code}&featureType=country&{params_query}&format=geojson"
    )
    return nominatim_search_url


def convert_nominatim_url_to_gdf(
    nominatim_search_url: str,
) -> gpd.GeoDataFrame:

    try:
        if nominatim_search_url is not None:
            # content = fetch_nominatim_search_content(nominatim_search_url)
            return process_nominatim_search_content(nominatim_search_url)

    except Exception as e:
        logging.error("Error reading and processing Nominatim search content from URL")
        raise ValueError("Failed to read and process Nominatim search content from") from e


def process_nominatim_search_content(
    search_url_content: str,
) -> gpd.GeoDataFrame:

    """
    Function to convert nominatim queried url to geodataframe

    Parameters:
    ----------
        nominatim_search_url: str - url of the nominatim query result

    Returns:
    -------
        gdf: geodataframe - geodataframe of the query result
        center_coors: list - array of the coordinates of the centroid of the geodataframe
    """

    try:
        gdf = gpd.read_file(search_url_content)

    except pd.errors.ParserError as e:
        logging.error(f"Error reading Nominatim search URL content: {e}")
        raise ValueError("Invalid format") from e

    try:
        gdf = gdf.to_crs(epsg=4326)

        # Calculate the centroid of the GeoDataFrame
        gdf_centroid = gdf.to_crs("+proj=cea").centroid.to_crs(gdf.crs)
        gdf_centroid = list(gdf_centroid.total_bounds)

        # Calculate the center of the GeoDataFrame
        center_x = (gdf_centroid[0] + gdf_centroid[2]) / 2  # Average of minx and maxx
        center_y = (gdf_centroid[1] + gdf_centroid[3]) / 2  # Average of miny and maxy
        gdf_center_coors = [center_y, center_x]

        return gdf, gdf_center_coors

    except Exception as e:
        raise ValueError(f"Error processing GeoDataFrame: {e}")


def filter_firms_points_within_country_area(
    firms_world_gdf: gpd.GeoDataFrame,
    country_gdf: gpd.GeoDataFrame
) -> gpd.GeoDataFrame:

    """

    Filters points from a GeoDataFrame that are within the polygons of another GeoDataFrame.

    :param firms_world_gdf: GeoDataFrame containing points.
    :param country_gdf: GeoDataFrame containing multipolygons.
    :return: GeoDataFrame containing only the points that are inside the specified area(s).
    """

    # Validate input GeoDataFrames
    if not isinstance(firms_world_gdf, gpd.GeoDataFrame):
        raise ValueError("FIRMS data must be a GeoDataFrame")
    if not isinstance(country_gdf, gpd.GeoDataFrame):
        raise ValueError("Nominatim country area data must be a GeoDataFrame")

    # Check if GeoDataFrames have geometry data
    if 'geometry' not in firms_world_gdf.columns or 'geometry' not in country_gdf.columns:
        raise ValueError("One or both of the GeoDataFrames do not have geometry data")

    # Check if GeoDataFrames are empty
    if firms_world_gdf.empty or country_gdf.empty:
        raise ValueError("One or both of the GeoDataFrames is empty")

    # Ensure the dataframes have the same coordinate reference system (CRS)
    try:
        if firms_world_gdf.crs != country_gdf.crs:
            firms_world_gdf = firms_world_gdf.to_crs(country_gdf.crs)
    except Exception as e:
        raise ValueError("Error in transforming CRS of the GeoDataFrame: " + str(e))

    # Filter points that are within the polygons
    try:
        within_area = firms_world_gdf.geometry.apply(
            lambda point: any(point.within(polygon) for polygon in country_gdf.geometry)
        )
    except Exception as e:
        raise ValueError("Error in filtering points within country area: " + str(e))

    filtered_gdf = firms_world_gdf[within_area]

    return filtered_gdf


def display_firms_points_within_country_boundary(
    filtered_firms_gdf: gpd.GeoDataFrame,
    country_gdf: gpd.GeoDataFrame,
    country_centroid: list
) -> st_folium:

    """
    Function to display the map of the geodataframe

    Parameters:
    ----------
        gdf: geodataframe - geodataframe of the query result
        centroid: narray - array of the coordinates of the centroid of the geodataframe

    Returns:
    -------
        st_map: streamlit-folium map - map of the geodataframe
    """

    # Validate input GeoDataFrames
    if not isinstance(filtered_firms_gdf, gpd.GeoDataFrame):
        raise ValueError("filtered_firms_gdf must be a GeoDataFrame")
    if not isinstance(country_gdf, gpd.GeoDataFrame):
        raise ValueError("country_gdf must be a GeoDataFrame")

    # Validate country_centroid
    if not isinstance(country_centroid, list) or len(country_centroid) != 2:
        raise ValueError("country_centroid must be a list of two coordinates (latitude, longitude)")

    # Check if GeoDataFrames are empty
    if filtered_firms_gdf.empty or country_gdf.empty:
        raise ValueError("One or both of the GeoDataFrames is empty")

    try:
        foliumMap = folium.Map(location=country_centroid, zoom_start=5, tiles="CartoDB positron")

        colors = [
            "darkred",
            "red",
            "darkorange",
            "orange",
            "orange",
            "beige",
            "beige",
            "lightgray",
            "lightgray",
            "gray",
        ]

        # Add a marker for each point in the data, with a color based on datetime_rank
        folium.GeoJson(
            filtered_firms_gdf,
            marker=folium.Marker(icon=folium.Icon(icon="fire", color="gray")),
            tooltip=folium.GeoJsonTooltip(
                fields=["acq_datetime", "confidence", "days_ago"],
                aliases=["Fire Detected On: ", "Detection Confidence: ", "Days Ago: "],
            ),
            style_function=lambda x: {
                "markerColor": colors[x["properties"]["days_ago"]]
                if x["properties"]["days_ago"] is not None else "gray"
            },
        ).add_to(foliumMap)

        folium.GeoJson(
            data=country_gdf,
            name="Country",  # Optional: give a name to the layer
            tooltip=folium.GeoJsonTooltip(
                fields=["display_name"],  # Field(s) to be shown in the tooltip
                aliases=["Country: "]  # Tooltip alias for the field
            ),
            style_function=lambda feature: {
                'fillColor': '#228B22',  # Set fill color, you can customize it
                'color': 'orange',        # Set border color, you can customize it
                'weight': 1,             # Border thickness
                'fillOpacity': 0.5       # Fill opacity
            }
        ).add_to(foliumMap)

        # Optionally, add a layer control to toggle layers on/off
        folium.LayerControl().add_to(foliumMap)

        st_map = st_folium(foliumMap, width=800, height=500)

        return st_map

    except Exception as e:
        raise ValueError(f"Error in displaying map: {e}")
