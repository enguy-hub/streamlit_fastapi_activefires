import json
import requests
import streamlit as st

from services.firms_nominatim_service import (
    get_account_status,
    get_current_transaction_count,
    convert_firms_urls_to_combined_gdf,
    convert_nominatim_url_to_gdf,
    filter_firms_points_within_country_area,
    display_firms_points_within_country_boundary
)
from models.firms_nominatim_models import (
    nominatim_country_codes,
)


# Function to get the world FIRMS data and keep it in cache to save transactions usage
@st.cache_data
def grabbing_firms_world_data(response_firms_urls: tuple, inputed_key: str):
    """
    Function to get the world FIRMS data and keep it in cache to save transactions usage
    """
    try:
        # # Check account status
        # account_status = get_account_status(inputed_key)
        # st.write("Current status of the FIRMS API usage")
        # st.dataframe(account_status.astype(str))

        # Start counting transactions
        start_count = get_current_transaction_count(inputed_key)
        firms_world_gdf = convert_firms_urls_to_combined_gdf(response_firms_urls)
        end_count = get_current_transaction_count(inputed_key)

        st.write("**%i** transactions were used" % (end_count - start_count))

        return firms_world_gdf

    except requests.HTTPError as e:
        if e.response.status_code == 403:
            st.error(
                "HTTP Error 403: The access limit of your FIRMS key is reached. "
                + "Try again in 10 minutes or use a different key")
        else:
            st.error(f"HTTP error occurred: {e}")
        raise
    except Exception as e:
        st.error(f"Error in grabbing FIRMS world data: {e}")
        raise


def set_state(i, country_code=None):
    st.session_state.stage = i
    # st.session_state.last_inputed_key = str()
    # st.session_state.inputed_key = str()
    # st.session_state.firms_world_gdf = None


# @st.cache
def firms_points_in_queried_aoi_map():
    if "stage" not in st.session_state:
        st.session_state.stage = 0

    # Stage 0: Input FIRMS Map Key
    if st.session_state.stage >= 0:

        st.write(
            "Get a FIRMS Map Key from the bottom of this page: https://firms.modaps.eosdis.nasa.gov/api/area/"
        )

        inputed_key = st.text_input(
            "Please enter your FIRMS Map Key in the text box below",
            on_change=set_state, args=[1]
        )
        st.session_state.inputed_key = inputed_key  # Store the inputed key in the session state

    # Stage 1: Fetch data if key has changed
    if st.session_state.stage >= 1:

        # st.write(f'Entered FIRMS map key: "{inputed_key}"')

        # FIRMS API input
        inputs_firms = {"firms_key": inputed_key}
        response_firms_urls = requests.post(
            "http://localhost:8000/create/firms_csv_urls",
            data=json.dumps(inputs_firms),
        ).json()
        # st.text(f"The URLs to query FIRMS Data of the last 9 days: \n{response_firms_urls}")
        response_firms_urls = tuple(response_firms_urls)

        # Check if inputed_key has changed
        if "last_inputed_key" not in st.session_state or (
                st.session_state.last_inputed_key != st.session_state.inputed_key
        ):
            firms_world_gdf = grabbing_firms_world_data(response_firms_urls, inputed_key)
            st.session_state.last_inputed_key = inputed_key  # Update the last inputed_key
            st.session_state.firms_world_gdf = firms_world_gdf  # Store the fetched data in the session state
        else:
            # Use cached data
            firms_world_gdf = st.session_state.firms_world_gdf

        # Check account status
        account_status = get_account_status(inputed_key)
        st.write("Current status of the FIRMS API usage")
        st.dataframe(account_status.astype(str))

        st.button("Select Country", on_click=set_state, args=[2])

    # Stage 2: Select country code and display data
    if st.session_state.stage >= 2:

        st.write(
            "From this list of OSM country codes: https://wiki.openstreetmap.org/wiki/Nominatim/Country_Codes"
        )
        entered_country_code = st.selectbox(
            "Select the country code that you want to display FIRMS data",
            nominatim_country_codes.__args__,
            index=None,
            placeholder="Select the country code ....",
            on_change=set_state,
            args=[3],
        )

    # Stage 3: Display data
    if st.session_state.stage >= 3:

        # if "selected_country_code" in st.session_state and st.session_state.selected_country_code is not None:

        if entered_country_code is not None:

            # st.write(f"Selected country code: {entered_country_code}")

            # Nominatim Search API input
            inputs_nominatim = {"country_code": entered_country_code}

            response_nominatim_url = requests.post(
                "http://localhost:8000/create/nominatim_search_url",
                data=json.dumps(inputs_nominatim),
            ).json()

            country_gdf, country_center = convert_nominatim_url_to_gdf(response_nominatim_url)
            # print("\n", country_gdf, "\n")

            filtered_firms_gdf = filter_firms_points_within_country_area(firms_world_gdf, country_gdf)
            # print("\n", filtered_firms_gdf, "\n")

            if not filtered_firms_gdf.empty:
                st.write(f"FIRMS data of the last **9 days** for **{entered_country_code}** ....")
                st.dataframe(filtered_firms_gdf.astype(str))

                display_firms_points_within_country_boundary(filtered_firms_gdf, country_gdf, country_center)

                st.text("Awesome!! Select another Country Code to try again!!!")

                st.button("Try Again With A New Map Key?", on_click=set_state, args=[0])

            else:
                print("No FIRMS data found. Please select another country from the list above!!!")
                st.text("No FIRMS data found. Please select another country from the list above!!!")

        else:
            print("No country code selected. Please select a country code from the list above!!!")
            st.text("No country code selected. Please select a country code from the list above!!!")


def main():
    APP_TITLE = "FastAPI Streamlit - Active Fires - Demo App"
    st.title(APP_TITLE)
    st.header("Display Active Fires From FIRMS Data For Selected Country")

    # Start the app
    firms_points_in_queried_aoi_map()


if __name__ == "__main__":
    main()
