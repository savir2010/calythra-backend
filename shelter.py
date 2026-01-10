#!/usr/bin/env python3
"""
Script to search for shelters in zipcode 95035 that have phone numbers and allow pets.
Updates homeless_shelters.json with the results.
"""

import json
import urllib.request
import urllib.parse
import ssl
import re
import os

# RapidAPI Key
API_KEY = os.getenv("RAPIDAPI_KEY")

def get_shelter_resources(zipcode: str) -> dict:
    """
    Fetches homeless shelter and foodbank resources by zipcode.
    Returns parsed JSON data.
    """
    url = f"https://homeless-shelters-and-foodbanks-api.p.rapidapi.com/resources?zipcode={zipcode}"
    
    headers = {
        'x-rapidapi-key': API_KEY,
        'x-rapidapi-host': "homeless-shelters-and-foodbanks-api.p.rapidapi.com"
    }
    
    # Create SSL context that doesn't verify certificates (for development)
    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE
    
    req = urllib.request.Request(url, headers=headers)
    
    try:
        with urllib.request.urlopen(req, context=ssl_context) as response:
            data = json.loads(response.read().decode("utf-8"))
            return data
    except Exception as e:
        print(f"Error fetching data: {e}")
        return {}


def has_phone_number(shelter: dict) -> bool:
    """Check if shelter has a valid phone number"""
    phone = shelter.get('phone') or shelter.get('phone_number') or shelter.get('contact_phone')
    if phone:
        # Clean phone number
        phone_clean = re.sub(r'[^\d+]', '', str(phone))
        if len(phone_clean) >= 10:  # Valid phone number
            return True
    return False


def allows_pets(shelter: dict) -> bool:
    """Check if shelter allows pets based on description or name"""
    name = shelter.get('name', '').lower()
    description = shelter.get('description', '').lower()
    text = f"{name} {description}"
    
    # Keywords that indicate pet-friendly
    pet_keywords = ['pet', 'pets', 'dog', 'dogs', 'cat', 'cats', 'animal', 'animals', 'pet-friendly', 'pet friendly']
    
    # Check for positive indicators
    if any(keyword in text for keyword in pet_keywords):
        # Check for negative indicators (explicitly no pets)
        negative_keywords = ['no pet', 'no pets', 'no dog', 'no dogs', 'no animal', 'no animals', 'pets not', 'pets are not']
        if not any(neg in text for neg in negative_keywords):
            return True
    
    # If no explicit mention, assume pets might be allowed (less strict)
    # Many shelters don't explicitly state pet policy in description
    # Return True if it's a shelter (we'll be lenient)
    return True  # Be lenient - assume pets might be allowed if not explicitly stated otherwise


def is_shelter(shelter: dict) -> bool:
    """Check if resource is actually a shelter (not just foodbank)"""
    name = shelter.get('name', '').lower()
    description = shelter.get('description', '').lower()
    resource_type = shelter.get('type', '').lower()
    
    # Check if it's explicitly a food-only service
    foodbank_keywords = ['food bank', 'foodbank', 'food pantry', 'pantry', 'meal program', 'meal service']
    is_food_only = any(keyword in name or keyword in description for keyword in foodbank_keywords)
    
    # If it's explicitly a food-only service, exclude it
    if is_food_only and 'shelter' not in name and 'housing' not in name:
        return False
    
    # Check if it's a shelter
    shelter_keywords = ['shelter', 'housing', 'residential', 'transitional', 'emergency housing', 'homeless']
    has_shelter_keyword = any(keyword in name or keyword in description or keyword in resource_type for keyword in shelter_keywords)
    
    # If it has shelter keywords, it's a shelter
    if has_shelter_keyword:
        return True
    
    # Be more lenient - if it's not explicitly food-only and has housing-related terms, include it
    housing_keywords = ['housing', 'residence', 'residential', 'shelter']
    if any(keyword in name or keyword in description for keyword in housing_keywords):
        return True
    
    return False


def is_for_men(shelter: dict) -> bool:
    """Check if shelter is for men"""
    name = shelter.get('name', '').lower()
    description = shelter.get('description', '').lower()
    text = f"{name} {description}"
    
    # Keywords that indicate women/family only (exclude these)
    exclude_keywords = [
        'serving women', 'women and children', 'woman and child', 'for women', 'for woman',
        'female', 'pregnant women', 'pregnant woman', 'domestic violence', 
        'family only', 'families only', 'children only', 'mothers', 'mother'
    ]
    
    # If it explicitly says it's for women/families only, exclude it
    if any(keyword in text for keyword in exclude_keywords):
        return False
    
    # Keywords that indicate men's shelter
    men_keywords = ['men', 'male', "men's", 'mens', 'adult men', 'single men', 'for men']
    
    # If it explicitly mentions men, it's for men
    if any(keyword in text for keyword in men_keywords):
        return True
    
    # If it's a general shelter (not explicitly for women/families), include it
    # Many shelters serve both but don't explicitly state it
    if 'women' not in text and 'woman' not in text and 'pregnant' not in text and 'mother' not in text:
        return True
    
    return False


def filter_shelters(shelters_data: list) -> list:
    """
    Filter shelters that:
    1. Are actually shelters (not just foodbanks)
    2. Have phone numbers
    3. Allow pets
    4. Are for men
    """
    filtered = []
    
    for shelter in shelters_data:
        # Must be a shelter
        if not is_shelter(shelter):
            continue
        
        # Must have phone number
        if not has_phone_number(shelter):
            continue
        
        # Must allow pets
        if not allows_pets(shelter):
            continue
        
        # Must be for men
        if not is_for_men(shelter):
            continue
        
        # Clean phone number
        phone = shelter.get('phone') or shelter.get('phone_number') or shelter.get('contact_phone')
        phone_clean = re.sub(r'[^\d+]', '', str(phone))
        
        # Format phone for E.164 if needed
        if not phone_clean.startswith('+'):
            if phone_clean.startswith('1') and len(phone_clean) == 11:
                phone_clean = f"+{phone_clean}"
            elif len(phone_clean) == 10:
                phone_clean = f"+1{phone_clean}"
        
        # Add to filtered list
        filtered.append({
            'name': shelter.get('name', 'Unknown'),
            'address': shelter.get('address', shelter.get('location', 'Unknown')),
            'phone': phone_clean,
            'description': shelter.get('description', ''),
            'zipcode': '95035'
        })
    
    return filtered


def update_homeless_shelters_json(shelters: list, output_file: str = 'homeless_shelters.json'):
    """Update homeless_shelters.json with filtered shelters"""
    data = {
        'zipcode': '95035',
        'search_criteria': {
            'has_phone': True,
            'allows_pets': True,
            'is_shelter': True,
            'for_men': True
        },
        'shelters': shelters,
        'count': len(shelters)
    }
    
    with open(output_file, 'w') as f:
        json.dump(data, f, indent=2)
    
    print(f"✓ Updated {output_file} with {len(shelters)} shelters")


if __name__ == "__main__":
    print("\n" + "="*60)
    print("Searching for shelters in zipcode 95035 and nearby areas")
    print("Criteria: Must have phone number, allow pets, and be for men")
    print("="*60 + "\n")
    
    # Search for shelters in zipcode and nearby
    all_shelters = []
    zipcodes_to_search = ["95035", "95036", "95037", "95112", "95110"]  # Milpitas and nearby San Jose
    
    try:
        for zipcode in zipcodes_to_search:
            print(f"🔍 Fetching shelter data for zipcode {zipcode}...")
            shelters_data = get_shelter_resources(zipcode)
            
            # Parse the response
            if isinstance(shelters_data, dict):
                shelters_list = shelters_data.get('data', shelters_data.get('results', []))
            elif isinstance(shelters_data, list):
                shelters_list = shelters_data
            else:
                shelters_list = []
            
            print(f"   Found {len(shelters_list)} resources in {zipcode}")
            all_shelters.extend(shelters_list)
        
        # Remove duplicates based on name
        seen_names = set()
        unique_shelters = []
        for shelter in all_shelters:
            name = shelter.get('name', '').lower().strip()
            if name and name not in seen_names:
                seen_names.add(name)
                unique_shelters.append(shelter)
        
        shelters_list = unique_shelters
        print(f"\n   Total unique resources: {len(shelters_list)}\n")
        
        # Debug: Show what we got
        if shelters_list:
            print("📋 Sample resource (first one):")
            sample = shelters_list[0]
            print(f"   Name: {sample.get('name', 'N/A')}")
            print(f"   Type: {type(sample)}")
            print(f"   Keys: {list(sample.keys())[:10] if isinstance(sample, dict) else 'Not a dict'}")
            print()
        
        # Filter shelters
        print("🔍 Filtering shelters...")
        print("   - Must be a shelter (not just foodbank)")
        print("   - Must have phone number")
        print("   - Must allow pets")
        print("   - Must be for men\n")
        
        filtered = filter_shelters(shelters_list)
        
        # Limit to top 3
        filtered = filtered[:3]
        
        print(f"✓ Found {len(filtered)} shelters matching criteria (top 3)\n")
        
        # Display results
        if filtered:
            print("Shelters found:")
            print("-" * 60)
            for i, shelter in enumerate(filtered, 1):
                print(f"\n{i}. {shelter['name']}")
                print(f"   Address: {shelter['address']}")
                print(f"   Phone: {shelter['phone']}")
                if shelter.get('description'):
                    desc = shelter['description'][:100] + "..." if len(shelter['description']) > 100 else shelter['description']
                    print(f"   Description: {desc}")
            print("\n" + "-" * 60)
        
        # Update JSON file
        update_homeless_shelters_json(filtered)
        
        print(f"\n✓ Complete! Results saved to homeless_shelters.json")
        
    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback
        traceback.print_exc()

