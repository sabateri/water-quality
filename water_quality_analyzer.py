import requests
import pandas as pd
import numpy as np
from geopy.geocoders import Nominatim
from geopy.distance import geodesic
import urllib.parse

class WaterQualityAnalyzer:
    """
    A class to analyze water quality data from the European Environment Agency.
    """
    def __init__(self, country_code="CH"):
        """
        Initialize the analyzer with country code and number of results to fetch.
        
        Args:
            country_code (str): ISO country code (e.g., 'FR' for France)
            n_hits (int): Number of results to fetch from the API
        """
        self.country_code = country_code
        self.n_hits = 0
        self.df = None
        self.geolocator = Nominatim(user_agent="water-quality-analyzer")
        self.thresholds_df = None
        self.threshold_date = '1999-01-01'
        self.filtered_df = None
        self.nearest_water_body = None


    def get_number_records(self):
        """
        Count how many records we have per country starting from a given date
        """
        sql_query = f"""
        SELECT COUNT(*) AS total_records
        FROM [WISE_SOE].[latest].[Waterbase_T_WISE6_DisaggregatedData] d
        JOIN [WISE_SOE].[latest].[Waterbase_S_WISE_SpatialObject_DerivedData] s
        ON d.monitoringSiteIdentifier = s.monitoringSiteIdentifier
        WHERE d.countryCode = '{self.country_code}'
        --AND d.phenomenonTimeSamplingDate >= '{self.threshold_date}'
        AND s.lat IS NOT NULL
        AND s.lon IS NOT NULL
        """

        encoded_query = urllib.parse.quote(sql_query)
        api_url = f"https://discodata.eea.europa.eu/sql?query={encoded_query}&p=1&nrOfHits=1&mail=null&schema=null"

        response = requests.get(api_url)
        response_json = response.json()    
        # get the number of records for a given country
        if response_json.get('results'):
            self.n_hits = response_json['results'][0]['total_records']
        else:
            self.n_hits = 0  # fallback if no results found
        return self.n_hits


    def fetch_data(self):
        """
        Fetch water quality data from the EEA DiscoData SQL API.
        """

        # First get the number of records to fetch
        n_hits = self.get_number_records()
        
        print('number of hits',n_hits)
        if n_hits == 0:
            print(f"No records found for country code {self.country_code}")
            return False
        
        sql_query = f"""
                        SELECT
                        d.monitoringSiteIdentifier,
                        d.observedPropertyDeterminandLabel AS contaminant,
                        d.observedPropertyDeterminandCode AS cas_code,
                        d.resultObservedValue,
                        d.resultUom,
                        d.phenomenonTimeSamplingDate AS sampling_date,
                        s.monitoringSiteName,
                        s.waterBodyName,
                        s.lat,
                        s.lon,
                        s.rbdName
                        FROM [WISE_SOE].[latest].[Waterbase_T_WISE6_DisaggregatedData] d
                        JOIN [WISE_SOE].[latest].[Waterbase_S_WISE_SpatialObject_DerivedData] s
                        ON d.monitoringSiteIdentifier = s.monitoringSiteIdentifier
                        WHERE d.countryCode = '{self.country_code}'
                        AND s.lat IS NOT NULL
                        AND s.lon IS NOT NULL
                    """
        
        # Remove extra whitespace and newlines (useful when the query is long, can cause problems)
        clean_query = " ".join(sql_query.split())

        # Encode the cleaned query
        encoded_query = urllib.parse.quote(clean_query)
        api_url = f'https://discodata.eea.europa.eu/sql?query={encoded_query}&p=1&nrOfHits={n_hits}&mail=null&schema=null'

        try:
            response = requests.get(api_url)
            response.raise_for_status()  # Raise exception for 4XX/5XX responses
            
            json_data = response.json()
            # Handle different JSON response structures
            if isinstance(json_data, dict) and 'results' in json_data:
                # Case 1: If the API returns a dictionary with a 'results' key
                rows = json_data['results']
            elif isinstance(json_data, list):
                # Case 2: If the API directly returns a list of rows
                rows = json_data
            else:
                print(f"Unexpected JSON structure: {type(json_data)}")
                if isinstance(json_data, dict):
                    print(f"Keys: {json_data.keys()}")
                return False
            
            # Convert to DataFrame
            self.df = pd.DataFrame(rows)
            
            # Convert coordinates to float (they might be strings from the API)
            self.df['lat'] = pd.to_numeric(self.df['lat'], errors='coerce')
            self.df['lon'] = pd.to_numeric(self.df['lon'], errors='coerce')
            
            # Convert sampling date to datetime
            self.df['sampling_date'] = pd.to_datetime(
                self.df['sampling_date'], errors='coerce'
            )
            
            # Convert result value to float for calculations
            self.df['resultObservedValue'] = pd.to_numeric(self.df['resultObservedValue'], errors='coerce')
            
            print(f"Successfully loaded {len(self.df)} water quality records")
            return True
            
        except requests.exceptions.RequestException as e:
            print(f"API request error: {e}")
        except ValueError as e:
            print(f"JSON parsing error: {e}")
            if 'response' in locals():
                print(f"Response content: {response.text[:200]}...")  # Print first 200 chars
        except Exception as e:
            print(f"Unexpected error: {e}")
            
        return False

    def get_coordinates_from_postal(self, postal_code, country_code=None):
        """
        Get coordinates from a postal code.

        Args:
            postal_code (str): Postal code to geocode
            
        Returns:
            tuple: (latitude, longitude) or None if not found
        """

        if country_code is None:
            country_code = self.country_code

        try:
            location = self.geolocator.geocode({"postalcode": postal_code, "country": country_code})
            if location:
                return (location.latitude, location.longitude)
            else:
                print(f"Could not geocode postal code: {postal_code}")
                return None
        except Exception as e:
            print(f"Geocoding error: {e}")
            return None
        
    def find_nearest_station(self, user_coords, num_stations=1):
        self.df["distance_km"] = self.df.apply(
            lambda row: geodesic(user_coords, (row["lat"], row["lon"])).km, axis=1
        )
        # Calculate distance to each station
        self.df["distance_km"] = self.df.apply(
                            lambda row: geodesic(user_coords, (row["lat"], row["lon"])).km 
                            if pd.notnull(row["lat"]) and pd.notnull(row["lon"]) else float('inf'),
                            axis=1
                            )           
        nearest = self.df.sort_values("distance_km").head(num_stations)

        # Store the nearest water body name for later use
        if not nearest.empty:
            self.nearest_water_body = nearest['waterBodyName'].iloc[0]
            
        return nearest
    

    def load_thresholds(self, filepath):
        """
        Load contaminant threshold values from CSV.
        
        Args:
            filepath (str): Path to CSV file with contaminant thresholds
        """
        try:
            self.thresholds_df = pd.read_csv(filepath)
            # Standardize contaminant names for matching
            self.thresholds_df['contaminant'] = self.thresholds_df['contaminant'].str.lower()
            print(f"Loaded {len(self.thresholds_df)} contaminant thresholds_df")
            return True
        except Exception as e:
            print(f"Error loading thresholds: {e}")
            return False
    
    def filter_by_water_body(self, water_body_name=None):
            """
            Filter data by water body name and drop duplicates, keeping the most recent 
            measurement for each contaminant.
            
            Args:
                water_body_name (str, optional): Water body name to filter by. 
                                                If None, uses the nearest water body.
            
            Returns:
                DataFrame: Filtered dataframe
            """
            import pandas as pd
            
            if water_body_name is None:
                if self.nearest_water_body is None:
                    print("No nearest water body found. Please run find_nearest_station first.")
                    return None
                water_body_name = self.nearest_water_body
                
            # Filter by water body name
            self.filtered_df = self.df[self.df["waterBodyName"] == water_body_name].copy()
            
            # Sort by sampling date (descending) and drop duplicates
            self.filtered_df = self.filtered_df.sort_values('sampling_date', ascending=False).drop_duplicates(subset='contaminant', keep='first')
            
            print(f"Filtered to {len(self.filtered_df)} unique contaminants in {water_body_name}")
            return self.filtered_df

    def massage_columns(self, df=None):
        """
        Modify some of the columns of the dataframe
        
        Args:
            df (DataFrame, optional): Dataframe to modify. If None, uses self.filtered_df.
            
        Returns:
            DataFrame: Modified dataframe
        """
        if df is None:
            if self.filtered_df is None:
                print("No filtered dataframe found. Please run filter_by_water_body first.")
                return None
            df = self.filtered_df

        df['contaminant'] = df['contaminant'].str.lower()
        df['cas_code'] = df['cas_code'].str.lower()
        df['resultUom'] = df['resultUom'].str.replace('ug/kg','ug/L')
        # remove some of the prefixes of the codes
        df['cas_code'] = df['cas_code'].str.replace('cas_', '')
        df['cas_code'] = df['cas_code'].str.replace('eea_', '')
        # Make sure the columns have proper types
        df['resultObservedValue'] = df['resultObservedValue'].astype(float)  # ensure it's a float
        df['resultUom'] = df['resultUom'].astype(str)  # ensure it's a float

        self.filtered_df = df
        return self.filtered_df    

    def convert_units(self, df=None):
        """
        Create a new column with values all in ug/L
        
        Args:
            df (DataFrame, optional): Dataframe to modify. If None, uses self.filtered_df.
            
        Returns:
            DataFrame: Modified dataframe
        """
        if df is None:
            if self.filtered_df is None:
                print("No filtered dataframe found. Please run filter_by_water_body first.")
                return None
            df = self.filtered_df

        df['resultObservedValue_ug_L'] = df.apply(
            lambda row: (row['resultObservedValue'] * 1000 if row['resultUom'] == 'mg/L' or row['resultUom'] == 'mg{NO2}/L' or row['resultUom'] == 'mg{NH4}/L'
                                                                or row['resultUom'] == 'mg{P}/L' or row['resultUom'] == 'mg{C}/L' or row['resultUom'] == 'mg{N}/L'
                                                                or row['resultUom'] == 'mg{NO3}/L'
                                                                else row['resultObservedValue'] if row['resultUom'] == 'ug/L'
                                                                else -1) # -1 for the units that are not recognized
                                                                ,
            axis=1
        )

        self.filtered_df = df
        return self.filtered_df
    

    def analyze_contaminants(self, df=None):
        """
        Analyze contaminants at a specific monitoring station.
        
        Args:
            df (DataFrame, optional): Dataframe to analyze. If None, uses self.filtered_df.
            
        Returns:
            DataFrame: Analysis results with threshold comparisons
        """

        if df is None:
            if self.filtered_df is None:
                print("No filtered dataframe found. Please run filter_by_water_body first.")
                return None
            df = self.filtered_df
            
        if self.thresholds_df is None:
            print("No thresholds loaded. Please run load_thresholds first.")
            return None
        

        merged_df = df.merge(self.thresholds_df,on="contaminant", how="left")
        # calculate if a given contaminant exceeds the recommended limit
        merged_df['exceeds_limit'] = merged_df['resultObservedValue_ug_L'] >= merged_df['limit']
        # calculate how many times a given compound surpasses the limit
        merged_df['exceeds_times'] = merged_df['resultObservedValue_ug_L'] / merged_df['limit']
        merged_df.head()
        return merged_df
    

    def full_analysis(self, postal_code, threshold_filepath):
            """
            Perform a complete analysis workflow from postal code to contaminant analysis.
            
            Args:
                postal_code (str): Postal code to analyze
                threshold_filepath (str): Path to threshold file
                
            Returns:
                tuple: (nearest_station, analysis_results)
            """
            # Get coordinates from postal code
            coords = self.get_coordinates_from_postal(postal_code)
            if not coords:
                print(f"Could not geocode postal code {postal_code}")
                return None, None
                
            # Find nearest station
            nearest_station = self.find_nearest_station(coords, num_stations=1)
            if nearest_station.empty:
                print("No monitoring stations found")
                return nearest_station, None
                
            # Load thresholds
            if not self.load_thresholds(threshold_filepath):
                print("Failed to load thresholds")
                return nearest_station, None
                
            # Filter by water body
            self.filter_by_water_body()
            
            # Process data
            self.massage_columns()
            self.convert_units()
            
            # Analyze contaminants
            analysis_results = self.analyze_contaminants()
            
            return nearest_station, analysis_results