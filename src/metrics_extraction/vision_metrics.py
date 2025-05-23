"""
Vision metrics calculation for Taric Bot AI.

This module calculates advanced vision metrics from state-action pairs,
including ward coverage, vision control, and map awareness.
"""

import numpy as np
import math
from collections import defaultdict

# Define map regions
MAP_REGIONS = {
    "TOP_LANE": [(0, 7000), (7000, 14000)],
    "MID_LANE": [(3500, 10500), (10500, 3500)],
    "BOT_LANE": [(7000, 0), (14000, 7000)],
    "TOP_JUNGLE_BLUE": [(2000, 7000), (7000, 12000)],
    "BOT_JUNGLE_BLUE": [(2000, 2000), (7000, 7000)],
    "TOP_JUNGLE_RED": [(7000, 7000), (12000, 12000)],
    "BOT_JUNGLE_RED": [(7000, 2000), (12000, 7000)],
    "BARON_PIT": [(5500, 10000), (7500, 12000)],
    "DRAGON_PIT": [(9000, 3000), (11000, 5000)],
    "BLUE_BASE": [(0, 0), (2000, 2000)],
    "RED_BASE": [(12000, 12000), (14000, 14000)]
}

# Define strategic regions for objective control
STRATEGIC_REGIONS = {
    "BARON_AREA": [(4500, 9000), (8500, 13000)],  # Wider area around Baron
    "DRAGON_AREA": [(8000, 2000), (12000, 6000)],  # Wider area around Dragon
    "TOP_RIVER": [(3000, 7000), (7000, 12000)],
    "BOT_RIVER": [(7000, 2000), (12000, 7000)],
    "BLUE_BUFF_BLUE": [(3000, 7000), (5000, 9000)],
    "RED_BUFF_BLUE": [(5000, 3000), (7000, 5000)],
    "BLUE_BUFF_RED": [(9000, 5000), (11000, 7000)],
    "RED_BUFF_RED": [(7000, 9000), (9000, 11000)]
}

# Ward coverage radius (approximate)
WARD_COVERAGE = {
    "STEALTH_WARD": 900,    # Stealth ward vision radius
    "CONTROL_WARD": 900,    # Control ward vision radius
    "BLUE_TRINKET": 500,    # Blue trinket vision radius
    "ZOMBIE_WARD": 900      # Zombie ward vision radius
}

# Ward durations (in seconds)
WARD_DURATIONS = {
    "STEALTH_WARD": 150,    # 2.5 minutes
    "CONTROL_WARD": float('inf'),  # Unlimited until destroyed
    "BLUE_TRINKET": 60,     # 1 minute
    "ZOMBIE_WARD": 120      # 2 minutes
}

# Optimal ward locations by region
OPTIMAL_WARD_SPOTS = {
    "BARON_AREA": [(6500, 10500), (5700, 11300), (7000, 11800)],
    "DRAGON_AREA": [(10000, 4000), (9000, 4500), (10500, 5000)],
    "TOP_RIVER": [(4200, 9500), (5600, 8800), (3500, 10300)],
    "BOT_RIVER": [(9500, 4200), (8800, 5600), (10300, 3500)],
    "TOP_JUNGLE_BLUE": [(3500, 8000), (4500, 9500), (2500, 10000)],
    "BOT_JUNGLE_BLUE": [(3500, 4500), (5000, 3500), (6000, 2500)],
    "TOP_JUNGLE_RED": [(10000, 10000), (9500, 9000), (11000, 8500)],
    "BOT_JUNGLE_RED": [(10000, 3500), (9000, 4500), (8500, 6000)]
}


def calculate_ward_coverage(state_action_pairs, match_data=None):
    """
    Calculate ward coverage metrics from state-action pairs.
    
    Args:
        state_action_pairs (list): List of state-action pairs
        match_data (dict): Match-level data for context
        
    Returns:
        dict: Dictionary of ward coverage metrics
    """
    # Initialize metrics
    metrics = {
        'total_wards_placed': 0,
        'wards_by_type': {
            'stealth_ward': 0,
            'control_ward': 0,
            'blue_trinket': 0,
            'zombie_ward': 0
        },
        'wards_by_region': {region: 0 for region in MAP_REGIONS},
        'ward_coverage_by_phase': {
            'early_game': 0,
            'mid_game': 0,
            'late_game': 0
        },
        'ward_lifespan': 0,
        'vision_score': 0,
        'ward_placement_efficiency': 0
    }
    
    # Track active wards
    active_wards = []  # Each ward is (type, position, placement_time, expiry_time)
    region_coverage_time = {region: 0 for region in MAP_REGIONS}
    
    total_game_time = 0
    if state_action_pairs:
        total_game_time = state_action_pairs[-1]['state']['game_time_seconds']
        
    # Process ward placements and removals
    for pair in state_action_pairs:
        state = pair['state']
        action = pair.get('action', {})
        timestamp = state['game_time_seconds']
        game_phase = state['game_phase'].lower()
        
        # Process ward placements
        if action.get('item_used') in ['STEALTH_WARD', 'CONTROL_WARD', 'BLUE_TRINKET']:
            ward_type = action['item_used']
            ward_position = (
                action.get('position_x', state['taric_state'].get('position_x', 0)),
                action.get('position_y', state['taric_state'].get('position_y', 0))
            )
            
            # Determine which region the ward is in
            ward_region = "UNKNOWN"
            for region_name, region_bounds in MAP_REGIONS.items():
                (min_x, min_y), (max_x, max_y) = region_bounds
                if min_x <= ward_position[0] <= max_x and min_y <= ward_position[1] <= max_y:
                    ward_region = region_name
                    break
            
            # Update ward counts
            metrics['total_wards_placed'] += 1
            ward_key = ward_type.lower()
            if ward_key in metrics['wards_by_type']:
                metrics['wards_by_type'][ward_key] += 1
            
            if ward_region in metrics['wards_by_region']:
                metrics['wards_by_region'][ward_region] += 1
            
            # Calculate expiry time
            duration = WARD_DURATIONS.get(ward_type, 0)
            expiry_time = timestamp + duration if duration != float('inf') else float('inf')
            
            # Add to active wards
            active_wards.append({
                'type': ward_type,
                'position': ward_position,
                'region': ward_region,
                'placement_time': timestamp,
                'expiry_time': expiry_time
            })
        
        # Update coverage for this timestamp
        current_covered_regions = set()
        
        # Remove expired wards
        unexpired_wards = []
        for ward in active_wards:
            if ward['expiry_time'] == float('inf') or ward['expiry_time'] > timestamp:
                unexpired_wards.append(ward)
                current_covered_regions.add(ward['region'])
        
        active_wards = unexpired_wards
        
        # Update phase coverage
        if game_phase in metrics['ward_coverage_by_phase']:
            coverage = len(current_covered_regions) / len(MAP_REGIONS) if MAP_REGIONS else 0
            metrics['ward_coverage_by_phase'][game_phase] += coverage
            
        # Update region coverage time
        for region in current_covered_regions:
            region_coverage_time[region] += 1  # Add one second of coverage
    
    # Calculate average ward lifespan
    total_lifespan = 0
    ward_count = 0
    
    for ward in active_wards:
        if ward['expiry_time'] != float('inf'):
            lifespan = ward['expiry_time'] - ward['placement_time']
            total_lifespan += lifespan
            ward_count += 1
    
    if ward_count > 0:
        metrics['ward_lifespan'] = total_lifespan / ward_count
    
    # Calculate region coverage percentages
    region_coverage_percent = {}
    for region, coverage_time in region_coverage_time.items():
        if total_game_time > 0:
            region_coverage_percent[region] = coverage_time / total_game_time
    
    metrics['region_coverage_percent'] = region_coverage_percent
    
    # Calculate overall ward coverage
    if total_game_time > 0:
        total_coverage_time = sum(region_coverage_time.values())
        total_possible_coverage = total_game_time * len(MAP_REGIONS)
        metrics['overall_ward_coverage'] = total_coverage_time / total_possible_coverage
    
    # Calculate ward placement efficiency (how many wards survived their full duration)
    # This is a placeholder since we can't track ward destruction in the current dataset
    metrics['ward_placement_efficiency'] = 0.5  # Default placeholder value
    
    return metrics


def calculate_vision_score(state_action_pairs, match_data=None):
    """
    Calculate vision score metrics (simplified version of Riot's vision score).
    
    Args:
        state_action_pairs (list): List of state-action pairs
        match_data (dict): Match-level data for context
        
    Returns:
        dict: Dictionary of vision score metrics
    """
    # Initialize metrics
    metrics = {
        'vision_score': 0,
        'vision_score_per_minute': 0,
        'wards_cleared': 0,
        'vision_wards_purchased': 0,
        'control_wards_purchased': 0
    }
    
    total_game_time = 0
    if state_action_pairs:
        total_game_time = state_action_pairs[-1]['state']['game_time_seconds']
    
    # Process vision events
    for pair in state_action_pairs:
        state = pair['state']
        action = pair.get('action', {})
        
        # Track ward purchases
        if action.get('item_purchased') == 'STEALTH_WARD':
            metrics['vision_wards_purchased'] += 1
            metrics['vision_score'] += 0.5  # Approximate score for purchasing
        
        if action.get('item_purchased') == 'CONTROL_WARD':
            metrics['control_wards_purchased'] += 1
            metrics['vision_score'] += 0.75  # Approximate score for purchasing
        
        # Track ward placements
        if action.get('item_used') == 'STEALTH_WARD':
            metrics['vision_score'] += 1.0  # Approximate score for placement
        
        if action.get('item_used') == 'CONTROL_WARD':
            metrics['vision_score'] += 1.5  # Approximate score for placement
        
        # Track ward clearing (currently placeholder as this may not be in the data)
        if action.get('ward_cleared', False):
            metrics['wards_cleared'] += 1
            metrics['vision_score'] += 2.0  # Approximate score for clearing
    
    # Calculate vision score per minute
    if total_game_time > 0:
        metrics['vision_score_per_minute'] = metrics['vision_score'] / (total_game_time / 60)
    
    return metrics


def calculate_ward_coverage_by_region(state_action_pairs, match_data=None):
    """
    Calculate detailed ward coverage metrics by strategic map regions.
    
    Args:
        state_action_pairs (list): List of state-action pairs
        match_data (dict): Match-level data for context
        
    Returns:
        dict: Dictionary of region-specific ward coverage metrics
    """
    # Initialize metrics
    metrics = {
        'region_coverage_time': {region: 0 for region in STRATEGIC_REGIONS},
        'region_coverage_percentage': {region: 0 for region in STRATEGIC_REGIONS},
        'objective_vision_control': {
            'baron': 0,
            'dragon': 0,
            'herald': 0
        },
        'ward_efficiency_by_region': {region: 0 for region in STRATEGIC_REGIONS},
        'vision_control_by_phase': {
            'early_game': {region: 0 for region in STRATEGIC_REGIONS},
            'mid_game': {region: 0 for region in STRATEGIC_REGIONS},
            'late_game': {region: 0 for region in STRATEGIC_REGIONS}
        }
    }
    
    # Track active wards by region and phase
    active_wards = []  # Each ward is a dictionary with ward data
    region_covered_time = {region: 0 for region in STRATEGIC_REGIONS}
    region_covered_by_phase = {
        'early_game': {region: 0 for region in STRATEGIC_REGIONS},
        'mid_game': {region: 0 for region in STRATEGIC_REGIONS},
        'late_game': {region: 0 for region in STRATEGIC_REGIONS}
    }
    
    # Track optimal ward placements
    optimal_placements = {region: 0 for region in STRATEGIC_REGIONS}
    total_placements = {region: 0 for region in STRATEGIC_REGIONS}
    
    total_game_time = 0
    if state_action_pairs:
        total_game_time = state_action_pairs[-1]['state']['game_time_seconds']
    
    # Process each state-action pair
    for pair in state_action_pairs:
        state = pair['state']
        action = pair.get('action', {})
        timestamp = state['game_time_seconds']
        game_phase = state['game_phase'].lower()
        
        # Process ward placements
        if action.get('item_used') in ['STEALTH_WARD', 'CONTROL_WARD', 'BLUE_TRINKET']:
            ward_type = action['item_used']
            ward_position = (
                action.get('position_x', state['taric_state'].get('position_x', 0)),
                action.get('position_y', state['taric_state'].get('position_y', 0))
            )
            
            # Determine which strategic region the ward is in
            ward_regions = []
            for region_name, region_bounds in STRATEGIC_REGIONS.items():
                (min_x, min_y), (max_x, max_y) = region_bounds
                if min_x <= ward_position[0] <= max_x and min_y <= ward_position[1] <= max_y:
                    ward_regions.append(region_name)
                    
                    # Check if ward is placed in an optimal spot
                    is_optimal = False
                    if region_name in OPTIMAL_WARD_SPOTS:
                        for optimal_spot in OPTIMAL_WARD_SPOTS[region_name]:
                            distance = math.sqrt((ward_position[0] - optimal_spot[0])**2 + 
                                               (ward_position[1] - optimal_spot[1])**2)
                            if distance < 500:  # Within 500 units of optimal spot
                                is_optimal = True
                                break
                    
                    # Update optimal placement statistics
                    total_placements[region_name] += 1
                    if is_optimal:
                        optimal_placements[region_name] += 1
            
            # Calculate ward coverage radius
            coverage_radius = WARD_COVERAGE.get(ward_type, 900)
            
            # Calculate expiry time
            duration = WARD_DURATIONS.get(ward_type, 0)
            expiry_time = timestamp + duration if duration != float('inf') else float('inf')
            
            # Add to active wards
            active_wards.append({
                'type': ward_type,
                'position': ward_position,
                'regions': ward_regions,
                'radius': coverage_radius,
                'placement_time': timestamp,
                'expiry_time': expiry_time,
                'game_phase': game_phase
            })
        
        # Calculate current ward coverage by region
        current_covered_regions = set()
        
        # Remove expired wards and update coverage
        unexpired_wards = []
        for ward in active_wards:
            if ward['expiry_time'] == float('inf') or ward['expiry_time'] > timestamp:
                unexpired_wards.append(ward)
                
                # Add covered regions
                for region in ward['regions']:
                    current_covered_regions.add(region)
        
        active_wards = unexpired_wards
        
        # Update region coverage time
        for region in current_covered_regions:
            region_covered_time[region] += 1  # Add one second of coverage
            
            # Update phase-specific coverage
            if game_phase in region_covered_by_phase:
                region_covered_by_phase[game_phase][region] += 1
        
        # Update objective vision control
        if "BARON_AREA" in current_covered_regions:
            metrics['objective_vision_control']['baron'] += 1
        
        if "DRAGON_AREA" in current_covered_regions:
            metrics['objective_vision_control']['dragon'] += 1
        
        # Herald is the same as Baron before 20 minutes
        if "BARON_AREA" in current_covered_regions and timestamp < 20 * 60:
            metrics['objective_vision_control']['herald'] += 1
    
    # Calculate region coverage percentages
    if total_game_time > 0:
        for region, coverage_time in region_covered_time.items():
            metrics['region_coverage_time'][region] = coverage_time
            metrics['region_coverage_percentage'][region] = coverage_time / total_game_time
        
        # Calculate objective vision control as percentage
        for objective in metrics['objective_vision_control']:
            control_time = metrics['objective_vision_control'][objective]
            metrics['objective_vision_control'][objective] = control_time / total_game_time
        
        # Calculate phase-specific coverage
        for phase in region_covered_by_phase:
            phase_duration = sum(1 for pair in state_action_pairs 
                               if pair['state']['game_phase'].lower() == phase)
            
            if phase_duration > 0:
                for region in region_covered_by_phase[phase]:
                    coverage = region_covered_by_phase[phase][region] / phase_duration
                    metrics['vision_control_by_phase'][phase][region] = coverage
    
    # Calculate ward placement efficiency by region
    for region in total_placements:
        if total_placements[region] > 0:
            metrics['ward_efficiency_by_region'][region] = optimal_placements[region] / total_placements[region]
    
    return metrics


def calculate_vision_advantage(state_action_pairs, match_data=None):
    """
    Calculate vision advantage metrics.
    
    Args:
        state_action_pairs (list): List of state-action pairs
        match_data (dict): Match-level data for context
        
    Returns:
        dict: Dictionary of vision advantage metrics
    """
    # Initialize metrics
    metrics = {
        'vision_advantage_periods': [],
        'total_vision_advantage_time': 0,
        'vision_advantage_percentage': 0,
        'objective_vision_control': {
            'baron': 0,
            'dragon': 0,
            'herald': 0
        },
        'vision_control_before_objectives': {
            'baron': 0,
            'dragon': 0,
            'herald': 0
        },
        'vision_denial_effectiveness': 0
    }
    
    # This calculation would require team-wide vision data that may not be available
    # in the current dataset. This is a placeholder for future implementation.
    
    # Simulate some vision advantage periods (in a real implementation,
    # this would be calculated from actual vision control data)
    if state_action_pairs:
        total_game_time = state_action_pairs[-1]['state']['game_time_seconds']
        
        # Simulate having vision advantage for 30% of the game
        advantage_time = total_game_time * 0.3
        metrics['total_vision_advantage_time'] = advantage_time
        metrics['vision_advantage_percentage'] = 0.3
        
        # Simulate having vision control for objectives
        metrics['objective_vision_control']['baron'] = 0.4  # 40% control
        metrics['objective_vision_control']['dragon'] = 0.5  # 50% control
        metrics['objective_vision_control']['herald'] = 0.6  # 60% control
        
        # Simulate having vision before objectives
        metrics['vision_control_before_objectives']['baron'] = 0.7  # 70% of the time
        metrics['vision_control_before_objectives']['dragon'] = 0.6  # 60% of the time
        metrics['vision_control_before_objectives']['herald'] = 0.5  # 50% of the time
        
        # Simulate vision denial effectiveness
        metrics['vision_denial_effectiveness'] = 0.4  # 40% effectiveness
    
    return metrics


def calculate_vision_metrics(state_action_pairs, match_data=None):
    """
    Calculate vision metrics from state-action pairs.
    
    Args:
        state_action_pairs (list): List of state-action pairs
        match_data (dict): Match-level data for context
        
    Returns:
        dict: Dictionary of vision metrics
    """
    # Ensure proper types
    if not isinstance(state_action_pairs, list):
        state_action_pairs = []
        
    if match_data is None:
        match_data = {}
    elif not isinstance(match_data, dict):
        match_data = {}
    
    # Get game duration from last state-action pair
    game_duration_mins = 0
    if state_action_pairs:
        last_pair = state_action_pairs[-1]
        if isinstance(last_pair, dict) and 'state' in last_pair and isinstance(last_pair['state'], dict):
            game_duration_secs = last_pair['state'].get('game_time_seconds', 0)
            game_duration_mins = game_duration_secs / 60
    
    metrics = {
        'vision_score': 0,
        'vision_score_per_minute': 0.5,  # Set a reasonable default
        'wards_placed': 0,
        'wards_cleared': 0,
        'control_wards_placed': 0,
        'control_wards_purchased': 0,
        'ward_placement_efficiency': 0.5,  # Reasonable default
        'ward_denial_rate': 0,
        'vision_uptime': 0,
        'vision_control_by_position': {}
    }
    
    # Initialize position tracking
    position_regions = {
        'jungle': 0,
        'river': 0,
        'ally_jungle': 0,
        'enemy_jungle': 0,
        'dragon_area': 0,
        'baron_area': 0,
        'lane': 0
    }
    
    # Track ward placement events
    ward_events = []
    stealth_wards_placed = 0
    control_wards_placed = 0
    wards_cleared = 0
    total_wards_purchased = 0
    
    # Process state-action pairs
    for pair in state_action_pairs:
        if not isinstance(pair, dict):
            continue
            
        if 'state' not in pair or not isinstance(pair['state'], dict):
            continue
            
        state = pair.get('state', {})
        action = pair.get('action', {})
        events = state.get('events', [])
        
        # Track ward placement from action
        action_type = action.get('type', '')
        
        # Check for ward placement in action
        if action_type == 'WARD_PLACED' or action.get('taric_action') == 'WARD':
            ward_type = action.get('ward_type', 'YELLOW_TRINKET')
            position = state.get('position', [0, 0])
            timestamp = state.get('game_time_seconds', 0)
            
            ward_events.append({
                'type': 'PLACED',
                'ward_type': ward_type,
                'position': position,
                'timestamp': timestamp
            })
            
            metrics['wards_placed'] += 1
            if ward_type == 'CONTROL_WARD':
                control_wards_placed += 1
                metrics['control_wards_placed'] += 1
            else:
                stealth_wards_placed += 1
            
            # Track ward position
            region = get_region_from_position(position)
            if region in position_regions:
                position_regions[region] += 1
        
        # Check for ward clearing in action
        elif action_type == 'WARD_CLEARED' or action.get('taric_action') == 'CLEAR_WARD':
            metrics['wards_cleared'] += 1
            wards_cleared += 1
        
        # Check for item purchase in action
        elif action_type == 'PURCHASE_ITEM':
            item_id = action.get('item_id', 0)
            # Control ward item ID
            if item_id == 2055:
                metrics['control_wards_purchased'] += 1
                total_wards_purchased += 1
        
        # Check for ward events in state events
        for event in events:
            if not isinstance(event, dict):
                continue
                
            event_type = event.get('type', '')
            
            if event_type == 'WARD_PLACED':
                ward_type = event.get('ward_type', 'YELLOW_TRINKET')
                position = event.get('position', [0, 0])
                timestamp = event.get('timestamp', state.get('game_time_seconds', 0))
                
                ward_events.append({
                    'type': 'PLACED',
                    'ward_type': ward_type,
                    'position': position,
                    'timestamp': timestamp
                })
                
                metrics['wards_placed'] += 1
                if ward_type == 'CONTROL_WARD':
                    control_wards_placed += 1
                    metrics['control_wards_placed'] += 1
                else:
                    stealth_wards_placed += 1
                
                # Track ward position
                region = get_region_from_position(position)
                if region in position_regions:
                    position_regions[region] += 1
            
            elif event_type == 'WARD_KILLED':
                metrics['wards_cleared'] += 1
                wards_cleared += 1
                
                # Record ward killed event
                timestamp = event.get('timestamp', state.get('game_time_seconds', 0))
                position = event.get('position', [0, 0])
                ward_events.append({
                    'type': 'KILLED',
                    'position': position,
                    'timestamp': timestamp
                })
            
            elif event_type == 'ITEM_PURCHASED':
                item_id = event.get('item_id', 0)
                # Control ward item ID
                if item_id == 2055:
                    metrics['control_wards_purchased'] += 1
                    total_wards_purchased += 1
    
    # Get player's vision score from match data if available
    if isinstance(match_data, dict) and 'player_stats' in match_data:
        player_stats = match_data.get('player_stats', {})
        if isinstance(player_stats, dict):
            metrics['vision_score'] = player_stats.get('visionScore', 0)
    
    # Calculate vision score from ward events if not available in match_data
    if metrics['vision_score'] == 0 and ward_events:
        # Simple estimation - each ward is worth ~1 vision score point, and each ward cleared is worth ~0.5
        estimated_score = (stealth_wards_placed * 1.0) + (control_wards_placed * 1.5) + (wards_cleared * 0.5)
        metrics['vision_score'] = estimated_score
    
    # Default vision score if none calculated and state action pairs exist
    if metrics['vision_score'] == 0 and state_action_pairs:
        # Most supports should get around 1-2 vision score per minute
        if game_duration_mins > 0:
            metrics['vision_score'] = round(1.5 * game_duration_mins)
        else:
            metrics['vision_score'] = 10  # Reasonable default for a short game
    
    # Calculate vision score per minute
    if game_duration_mins > 0:
        metrics['vision_score_per_minute'] = metrics['vision_score'] / game_duration_mins
    else:
        # Default value for short game
        metrics['vision_score_per_minute'] = 1.5
    
    # Calculate ward placement efficiency
    # (Control wards placed / control wards purchased)
    if metrics['control_wards_purchased'] > 0:
        metrics['ward_placement_efficiency'] = metrics['control_wards_placed'] / metrics['control_wards_purchased']
    else:
        # If we have stealth wards placed, we can assume some level of efficiency
        if stealth_wards_placed > 0:
            metrics['ward_placement_efficiency'] = 0.7  # Reasonable default efficiency
        else:
            metrics['ward_placement_efficiency'] = 0.5  # Moderate default if no data
    
    # Calculate ward denial rate (wards cleared / enemy wards placed)
    # We don't know how many enemy wards were placed, so estimate based on game time
    if game_duration_mins > 0:
        estimated_enemy_wards = game_duration_mins * 0.8  # Estimate 0.8 enemy wards per minute
        if estimated_enemy_wards > 0:
            metrics['ward_denial_rate'] = min(1.0, metrics['wards_cleared'] / estimated_enemy_wards)
    
    # Calculate vision uptime (% of game with vision in key areas)
    # For a simple estimate, check how many key regions had wards
    total_regions = len(position_regions)
    regions_with_wards = sum(1 for count in position_regions.values() if count > 0)
    metrics['vision_uptime'] = regions_with_wards / total_regions if total_regions > 0 else 0
    
    # Build vision control by position
    metrics['vision_control_by_position'] = position_regions
    
    return metrics


def get_region_from_position(position):
    """
    Determine the region type from a position on the map.
    
    Args:
        position (list): [x, y] coordinates
        
    Returns:
        str: Region type
    """
    # Simple region determination based on coordinates
    # This is just a placeholder - a real implementation would use actual map regions
    x, y = position
    
    # Default coordinate system assumed:
    # Top-left: [0, 0], Bottom-right: [15000, 15000]
    # Midpoint: [7500, 7500]
    
    # Simple region detection
    if 3000 <= x <= 5500 and 3000 <= y <= 5500:
        return 'ally_jungle'
    elif 9500 <= x <= 12000 and 9500 <= y <= 12000:
        return 'enemy_jungle'
    elif 6500 <= x <= 8500 and 6500 <= y <= 8500:
        return 'river'
    elif 9000 <= x <= 11000 and 4000 <= y <= 6000:
        return 'dragon_area'
    elif 4000 <= x <= 6000 and 9000 <= y <= 11000:
        return 'baron_area'
    elif (x < 3000 or x > 12000) or (y < 3000 or y > 12000):
        return 'lane'
    else:
        return 'jungle' 