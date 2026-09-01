import pandas as pd
from datetime import datetime

def calculate_priority(df):
    """
    Calculates a transparent priority score for each maintenance task.
    No ML used here, just a clear rule-based heuristic.
    """
    # Formula: Give weightage to critical factors
    df['Priority_Score'] = (df['Criticality'] * 4) + (df['Urgency'] * 3) + (df['Asset_Importance'] * 2) + df['Overdue_Days']
    
    # Sort the tasks so the highest score is at the top
    return df.sort_values(by='Priority_Score', ascending=False)

def find_train_free_windows(schedule_df, section):
    """
    Finds gaps between trains in the given section.
    """
    # Get trains only for this section and sort by their start time
    sec_trains = schedule_df[schedule_df['Section'] == section].copy()
    sec_trains = sec_trains.sort_values(by='Start_Time')
    
    windows = []
    prev_end = None
    
    for index, row in sec_trains.iterrows():
        # Convert string times (e.g., "08:45") into time objects so we can subtract them
        curr_start = datetime.strptime(row['Start_Time'], '%H:%M')
        curr_end = datetime.strptime(row['End_Time'], '%H:%M')
        
        if prev_end is not None:
            # Calculate the gap in hours
            gap_delta = curr_start - prev_end
            gap_hours = gap_delta.total_seconds() / 3600.0
            
            if gap_hours > 0:
                windows.append({
                    'window_start': prev_end.strftime('%H:%M'),
                    'window_end': curr_start.strftime('%H:%M'),
                    'duration_hr': gap_hours
                })
        
        prev_end = curr_end
        
    # Sort windows so the largest time gap is at the top
    windows = sorted(windows, key=lambda x: x['duration_hr'], reverse=True)
    return windows

def generate_plan(section, maintenance_path='data/maintenance.csv', schedule_path='data/train_schedule.csv'):
    """
    The main logic to combine tasks into the best train-free window.
    """
    # 1. Load Data
    m_df = pd.read_csv(maintenance_path)
    s_df = pd.read_csv(schedule_path)
    
    # 2. Filter maintenance by section and calculate priority
    m_df = m_df[m_df['Section'] == section].copy()
    m_df = calculate_priority(m_df)
    
    # 3. Find Train-Free Windows
    windows = find_train_free_windows(s_df, section)
    
    if not windows:
        return None, "No train-free windows available in this section."
        
    # 4. Find the Best Block (Greedy Algorithm)
    best_window = windows[0] # Pick the largest gap
    
    # We only look at tasks that are safe to combine
    compatible_tasks = m_df[m_df['Can_Combine'] == True]
    
    selected_tasks = []
    max_duration_needed = 0.0 # Duration if tasks run parallel
    sum_durations = 0.0       # Duration if planned manually
    
    for index, task in compatible_tasks.iterrows():
        task_duration = task['Duration_hr']
        
        # If we add this task, what is the new block duration? 
        # (Because they work simultaneously, block time = longest task)
        new_max_duration = max(max_duration_needed, task_duration)
        
        # Check if they fit into our train-free window
        if new_max_duration <= best_window['duration_hr']:
            selected_tasks.append(task)
            max_duration_needed = new_max_duration
            sum_durations += task_duration
            
    if len(selected_tasks) == 0:
        return None, "No compatible maintenance tasks fit in the available windows."
        
    # Prepare the final output
    plan_details = {
        'window': best_window,
        'tasks': pd.DataFrame(selected_tasks),
        'before_duration_hr': sum_durations,
        'after_duration_hr': max_duration_needed,
        'time_saved_hr': sum_durations - max_duration_needed
    }
    
    return plan_details, "Success"
# --- QUICK TEST ---
if __name__ == "__main__":
    plan, message = generate_plan("Section_AB")
    print("Status:", message)
    if plan:
        print("\n--- Tasks Scheduled in this Window ---")
        print(plan['tasks'][['Task_ID', 'Department', 'Task_Type', 'Duration_hr']])