from typing import TypedDict


class AgentState(TypedDict, total=False):
    url: str

    # Scout output
    business_name: str
    business_description: str
    location: dict
    key_person: dict
    conversion_action: str
    business_model: str
    competitors: list[dict]
    target_keywords: list[str]

    # Raw data
    gsc_data: dict
    ga4_data: dict
    ahrefs_data: dict

    # Analysis output
    analysis: dict          # full analyst JSON output
    anomalies: list[str]

    # Implementation pipeline
    task_plan: list[dict]           # from planner
    generated_assets: list[dict]    # from content_agent
    implementation_log: list[dict]  # from wordpress_agent + gsc_actions_agent
    dev_briefs: list[dict]          # tasks needing manual developer work
    verify_list: list[str]          # URLs to check in 48h

    # Control
    errors: list[str]
