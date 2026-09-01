import os

# Create the data folder if it doesn't exist
os.makedirs('data', exist_ok=True)

# 1. Write the maintenance data
with open('data/maintenance.csv', 'w') as f:
    f.write("""Task_ID,Department,Section,Task_Type,Duration_hr,Criticality,Urgency,Overdue_Days,Asset_Importance,Can_Combine
T01,Engineering,Section_AB,Track Repair,2.0,5,4,2,5,True
T02,Electrical,Section_AB,OHE Inspection,1.5,4,3,0,4,True
T03,S&T,Section_AB,Signal Check,1.0,5,5,5,5,True
T04,Engineering,Section_BC,Rail Replacement,3.0,4,2,0,5,False
T05,Electrical,Section_BC,Wiring,2.0,3,3,1,4,True
T06,S&T,Section_CD,Sensor Fix,1.0,5,4,2,3,True
T07,Engineering,Section_CD,Ballast Cleaning,2.5,3,2,0,4,False
T08,Electrical,Section_AB,Insulator Swap,1.0,4,3,1,4,True
T09,S&T,Section_BC,Point Machine,1.5,5,4,3,5,True
T10,Engineering,Section_AB,Welding,1.5,4,4,1,4,True
T11,S&T,Section_AB,Cable Repair,2.0,4,3,2,4,True
T12,Electrical,Section_CD,Transformer Check,2.0,5,4,0,5,False
T13,Engineering,Section_BC,Bridge Inspection,4.0,5,5,10,5,False
T14,S&T,Section_CD,Relay Room Fix,1.5,4,3,1,4,True
T15,Electrical,Section_AB,Earthing,1.0,3,2,0,3,True
T16,Engineering,Section_CD,Sleepers Change,3.0,4,4,2,4,False
T17,S&T,Section_BC,Telecom Cable,1.0,3,2,0,3,True
T18,Electrical,Section_BC,Traction Motor,2.5,4,3,1,4,True
T19,Engineering,Section_AB,Joint Checking,1.0,3,3,1,4,True
T20,S&T,Section_CD,Panel Interlocking,2.0,5,4,3,5,False
""")

# 2. Write the train schedule data
with open('data/train_schedule.csv', 'w') as f:
    f.write("""Train_ID,Train_Name,Section,Start_Time,End_Time,Train_Type
TR101,Rajdhani Exp,Section_AB,06:00,06:30,Express
TR102,Shatabdi Exp,Section_AB,07:30,08:00,Express
TR103,Goods Train 1,Section_AB,08:15,08:45,Freight
TR104,Passenger 1,Section_AB,11:30,12:00,Passenger
TR105,Vande Bharat,Section_AB,12:30,13:00,Express
TR106,Duronto Exp,Section_AB,14:00,14:30,Express
TR107,Local Train 1,Section_AB,15:15,15:45,Passenger
TR108,Goods Train 2,Section_AB,16:30,17:15,Freight
TR109,Rajdhani Exp,Section_AB,18:00,18:30,Express
TR110,Night Mail,Section_AB,21:00,21:30,Express
""")

print("SUCCESS: Data files have been written perfectly!")