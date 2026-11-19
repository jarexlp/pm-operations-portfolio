// =============================================================================
// LIVE POWER BI STAR SCHEMA - POWER QUERY (M) CONNECTOR FOR SHAREPOINT ONLINE
// Set Power BI Parameter `SharePointSiteURL` to your tenant site before refresh.
// =============================================================================

// 1. PARAMETER: SharePointSiteURL
let
    SharePointSiteURL = "https://your-tenant.sharepoint.com/sites/operations-hub" meta [IsParameterQuery=true, Type="Text", IsParameterQueryRequired=true]
in
    SharePointSiteURL


// 2. QUERY: Fact_Realtime_Backlog (List: Leader_Backlog)
// Tracks real-time compliance status (Completed, Enrolled, Pending, Blocked)
let
    Source = SharePoint.Tables(SharePointSiteURL, [Implementation="2.0", ApiVersion=15]),
    BacklogList = Source{[Title="Leader_Backlog"]}[Items],
    #"Renamed Columns" = Table.RenameColumns(BacklogList,{
        {"ID", "Backlog_ID"},
        {"Title", "Course_Name"},
        {"field_1", "Employee_ID"},
        {"field_2", "Leader_Name"},
        {"field_3", "Persona"},
        {"field_4", "Country"},
        {"field_5", "Country_Code"},
        {"field_6", "Site"},
        {"field_7", "Status"},
        {"field_8", "Status_Detail"},
        {"field_9", "1Up_Manager_Name"},
        {"field_10", "1Up_Manager_Email"},
        {"Modified", "Last_Modified_Date"}
    }),
    #"Selected Columns" = Table.SelectColumns(#"Renamed Columns", {
        "Backlog_ID", "Course_Name", "Employee_ID", "Leader_Name", "Persona",
        "Country", "Country_Code", "Site", "Status", "Status_Detail",
        "1Up_Manager_Name", "1Up_Manager_Email", "Last_Modified_Date"
    }),
    #"Transform Types" = Table.TransformColumnTypes(#"Selected Columns",{
        {"Backlog_ID", Int64.Type},
        {"Course_Name", type text},
        {"Employee_ID", type text},
        {"Leader_Name", type text},
        {"Country", type text},
        {"Site", type text},
        {"Status", type text},
        {"Status_Detail", type text},
        {"Last_Modified_Date", type datetimezone}
    })
in
    #"Transform Types"


// 3. QUERY: Fact_Realtime_Calendar (List: Operations_Calendar)
// Tracks live capacity, consumed seats, and room occupancy rates
let
    Source = SharePoint.Tables(SharePointSiteURL, [Implementation="2.0", ApiVersion=15]),
    CalendarList = Source{[Title="Operations_Calendar"]}[Items],
    #"Renamed Columns" = Table.RenameColumns(CalendarList,{
        {"ID", "Session_ID"},
        {"Title", "Session_Code"},
        {"field_1", "Course_Name"},
        {"field_2", "Trainer_Facilitator"},
        {"field_3", "Session_Date"},
        {"field_4", "Start_Time"},
        {"field_5", "End_Time"},
        {"field_6", "Country"},
        {"field_7", "Modality"},
        {"field_8", "Max_Capacity"},
        {"field_9", "Current_Enrollment"},
        {"field_10", "Session_Status"}
    }),
    #"Calculate Vacancies" = Table.AddColumn(#"Renamed Columns", "Available_Seats", each [Max_Capacity] - [Current_Enrollment], Int64.Type),
    #"Calculate Occupancy Pct" = Table.AddColumn(#"Calculate Vacancies", "Occupancy_Rate", each if [Max_Capacity] > 0 then [Current_Enrollment] / [Max_Capacity] else 0, Percentage.Type),
    #"Transform Types" = Table.TransformColumnTypes(#"Calculate Occupancy Pct",{
        {"Session_ID", Int64.Type},
        {"Session_Code", type text},
        {"Course_Name", type text},
        {"Trainer_Facilitator", type text},
        {"Session_Date", type date},
        {"Country", type text},
        {"Modality", type text},
        {"Max_Capacity", Int64.Type},
        {"Current_Enrollment", Int64.Type},
        {"Session_Status", type text}
    })
in
    #"Transform Types"


// 4. QUERY: Fact_Realtime_Registrations (List: Session_Registrations)
// Transactional registration, attendance & cancellation ledger
let
    Source = SharePoint.Tables(SharePointSiteURL, [Implementation="2.0", ApiVersion=15]),
    RegList = Source{[Title="Session_Registrations"]}[Items],
    #"Renamed Columns" = Table.RenameColumns(RegList,{
        {"ID", "Registration_ID"},
        {"Title", "Registration_Code"},
        {"field_1", "Employee_ID"},
        {"field_2", "Employee_Name"},
        {"field_3", "Course_Name"},
        {"field_4", "Session_ID"},
        {"field_5", "Registration_Date"},
        {"field_6", "Attendance_Status"},
        {"Created", "Created_Date"},
        {"Modified", "Modified_Date"}
    }),
    #"Transform Types" = Table.TransformColumnTypes(#"Renamed Columns",{
        {"Registration_ID", Int64.Type},
        {"Employee_ID", type text},
        {"Employee_Name", type text},
        {"Course_Name", type text},
        {"Session_ID", type text},
        {"Attendance_Status", type text},
        {"Created_Date", type datetimezone},
        {"Modified_Date", type datetimezone}
    })
in
    #"Transform Types"
