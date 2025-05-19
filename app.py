from flask import Flask, render_template, request, jsonify
import pandas as pd
from water_quality_analyzer import WaterQualityAnalyzer
import os

app = Flask(__name__)

# Path to thresholds file
THRESHOLDS_PATH = os.path.join(os.path.dirname(__file__), 'data', 'world_contaminant_thresholds.csv')

@app.route('/')
def home():
    """Render the home page with the input form"""
    return render_template('index.html')

@app.route('/analyze', methods=['POST'])
def analyze():
    """Process user input and analyze water quality"""
    # Get form data
    country_code = request.form.get('country_code', '')
    postal_code = request.form.get('postal_code', '')
    
    # Validate input
    if not country_code or not postal_code:
        return jsonify({
            'success': False,
            'message': 'Please provide both country code and postal code'
        })
    
    # Initialize the analyzer
    analyzer = WaterQualityAnalyzer(country_code=country_code)
    
    # Try to fetch data
    if not analyzer.fetch_data():
        return jsonify({
            'success': False,
            'message': f'Failed to fetch water quality data for {country_code}'
        })
    
    # Perform full analysis
    nearest_station, analysis_results = analyzer.full_analysis(postal_code, THRESHOLDS_PATH)
    
    # Check if we found a station
    if nearest_station is None or nearest_station.empty:
        return jsonify({
            'success': False,
            'message': f'Could not find a monitoring station near postal code {postal_code}'
        })
    
    # Check if we have analysis results
    if analysis_results is None:
        return jsonify({
            'success': False,
            'message': 'Could not analyze water quality data'
        })
    
    # Process results for display
    station_info = {
        'name': nearest_station['monitoringSiteName'].iloc[0],
        'water_body': nearest_station['waterBodyName'].iloc[0],
        'distance_km': round(nearest_station['distance_km'].iloc[0], 2)
    }
    
    # Process contaminants data
    exceed_count = analysis_results['exceeds_limit'].sum()
    
    # Get contaminants exceeding limits
    exceeded_contaminants = []
    if exceed_count > 0:
        exceeded = analysis_results[analysis_results['exceeds_limit'] == True]
        for _, row in exceeded.iterrows():
            exceeded_contaminants.append({
                'name': row['contaminant'],
                'value': round(row['resultObservedValue_ug_L'], 2),
                'limit': round(row['limit'], 2),
                'times_exceeded': round(row['exceeds_times'], 1)
            })
    
    # Get all contaminants for complete data
    all_contaminants = []
    for _, row in analysis_results.iterrows():
        all_contaminants.append({
            'name': row['contaminant'],
            'value': round(row['resultObservedValue_ug_L'], 2) if not pd.isna(row['resultObservedValue_ug_L']) else None,
            'limit': round(row['limit'], 2) if not pd.isna(row['limit']) else None,
            'exceeds': bool(row['exceeds_limit']) if not pd.isna(row['exceeds_limit']) else False
        })
    
    # Return the results
    return jsonify({
        'success': True,
        'station': station_info,
        'contaminants': {
            'total_count': len(analysis_results),
            'exceeding_count': int(exceed_count),
            'exceeded': exceeded_contaminants,
            'all': all_contaminants
        }
    })

if __name__ == '__main__':
    app.run(debug=True)
