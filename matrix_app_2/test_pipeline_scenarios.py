#!/usr/bin/env python3
"""
Comprehensive Test Suite & Diagnostic Harness for UP Police Matrix Pipeline (matrix_app_2)
========================================================================================
Validates complex intelligence queries, multi-scenario handling, and 10 benchmark topics:
- Scenario 1: Multi-dimensional filtering (District, Date, Categories, Sentiment, Police Image, Fake News)
- Scenario 2: Event-wise Cross-Regional Propagation (Outside UP -> UP / Jantar Mantar -> Lucknow)
- Scenario 3: Incident Dissection & Historical Profile / Recurring Patterns
- 10 Benchmark Topics (UPSSSC, UPSI, DGP UPSC, Sonbhadra, Agra Police, Bahraich, Lekhpal, UPSDMA, Shahjahanpur, Agra Communal)

Usage:
    # Run in-process test using LangGraph async execution:
    python3 test_pipeline_scenarios.py --mode in-process

    # Run against active server endpoint:
    python3 test_pipeline_scenarios.py --mode server --url http://127.0.0.1:8123

    # Run specific scenario or topic filter:
    python3 test_pipeline_scenarios.py --filter "Sonbhadra"
    python3 test_pipeline_scenarios.py --scenario 2
"""

import os
import sys
import time
import json
import asyncio
import argparse
from datetime import datetime
from typing import Dict, Any, List, Optional

# ANSI Color formatting
C_RESET = "\033[0m"
C_BOLD = "\033[1m"
C_CYAN = "\033[96m"
C_GREEN = "\033[92m"
C_YELLOW = "\033[93m"
C_RED = "\033[91m"
C_BLUE = "\033[94m"
C_MAGENTA = "\033[95m"

# Test Scenarios and Benchmark Queries
TEST_SCENARIOS = [
    # =========================================================================
    # SCENARIO 1: COMPLEX MULTI-DIMENSIONAL FILTERING & POLICE SENTIMENT
    # =========================================================================
    {
        "id": "SC1_01",
        "scenario": 1,
        "title": "Viral Topic Ranking & District Breakdown",
        "query": "आज उत्तर प्रदेश के कौन से मामले सबसे ज्यादा वायरल हैं और किस जिले में सबसे ज्यादा चर्चा है?",
        "intent": "Virality aggregation by district and post count",
        "expected_tables": ["topic", "analyzed_data"],
        "expected_indicators": ["viral", "total_no_of_post", "primary_districts"],
    },
    {
        "id": "SC1_02",
        "scenario": 1,
        "title": "Negative Sentiment & Police Image Criticism",
        "query": "Show me posts with negative sentiment criticizing UP police conduct or delay in action over the last week.",
        "intent": "Negative sentiment filter against police entities / mentions",
        "expected_tables": ["analyzed_data", "sentiment_entities", "topic"],
        "expected_indicators": ["sentiment_label", "Negative", "police"],
    },
    {
        "id": "SC1_03",
        "scenario": 1,
        "title": "Heinous & Women/Child Crime Categorization",
        "query": "पिछले 15 दिनों में महिलाओं और बच्चों से संबंधित जघन्य अपराधों के कितने मामले दर्ज हुए हैं?",
        "intent": "Category filtering on CRIME, HEINOUS, WOMEN/CHILD sub-categories",
        "expected_tables": ["topic", "analyzed_data", "sub_category"],
        "expected_indicators": ["CRIME", "sub_category"],
    },
    {
        "id": "SC1_04",
        "scenario": 1,
        "title": "Fake News & Misinformation Tracking",
        "query": "Is there any flagged misinformation or fake news circulating on Twitter and WhatsApp?",
        "intent": "Platform filtering + Fake news subcategory or flagged posts",
        "expected_tables": ["analyzed_data", "post_bank"],
        "expected_indicators": ["core_source", "TWITTER", "is_flagged"],
    },
    {
        "id": "SC1_05",
        "scenario": 1,
        "title": "Caste / Religion Sensitive Incidents",
        "query": "सोनभद्र या आसपास के क्षेत्रों में जातिगत या धार्मिक तनाव से जुड़े मामलों का क्या स्टेटस है?",
        "intent": "Caste/Religion entity filter and district context",
        "expected_tables": ["analyzed_data", "topic", "district_internal_report"],
        "expected_indicators": ["caste_names", "religion_names", "Sonbhadra"],
    },

    # =========================================================================
    # SCENARIO 2: CROSS-REGIONAL EVENT ANALYSIS (OUTSIDE UP -> UP)
    # =========================================================================
    {
        "id": "SC2_01",
        "scenario": 2,
        "title": "Jantar Mantar Protest Spillover to UP (Lucknow)",
        "query": "दिल्ली जंतर मंतर पर जो विरोध प्रदर्शन शुरू हुआ था, क्या उसका प्रभाव लखनऊ या यूपी के अन्य शहरों में भी दिख रहा है?",
        "intent": "Cross-regional movement tracking (Delhi/Jantar Mantar to Lucknow)",
        "expected_tables": ["topic", "analyzed_data"],
        "expected_indicators": ["Jantar Mantar", "Lucknow", "PROTEST"],
    },
    {
        "id": "SC2_02",
        "scenario": 2,
        "title": "Influencer & Media Profiling at Incident Ground",
        "query": "हालिया धरना प्रदर्शन और विरोध स्थलों पर किन मुख्य मीडियाकर्मियों और इन्फ्लुएंसर्स ने सबसे ज्यादा पोस्ट और कवरेज किया है?",
        "intent": "Actor attribution via post_users, follower counts and verified status",
        "expected_tables": ["post_users", "analyzed_data", "monitor_profiles"],
        "expected_indicators": ["followers_count", "author_username", "is_verified"],
    },
    {
        "id": "SC2_03",
        "scenario": 2,
        "title": "Job & Exam Agitation Cross-District Correlation",
        "query": "यूपी में छात्र और युवा रोजगार, पेपर लीक या भर्ती परीक्षा को लेकर किन-किन जिलों में धरने की योजना बना रहे हैं?",
        "intent": "Employment/exam protest trend analysis across districts",
        "expected_tables": ["topic", "analyzed_data"],
        "expected_indicators": ["PROTEST", "primary_districts"],
    },

    # =========================================================================
    # SCENARIO 3: PAST INCIDENT DISSECTION & RECURRING PATTERNS
    # =========================================================================
    {
        "id": "SC3_01",
        "scenario": 3,
        "title": "Incident Dissection (Who was involved, what happened)",
        "query": "पिछले महीने आगरा में हुए विवाद की पूरी केस टाइमलाइन बताएं—कौन शामिल था और क्या कार्रवाई हुई?",
        "intent": "Comprehensive case summary: entities, actions, timeline",
        "expected_tables": ["topic", "analyzed_data", "district_internal_report", "ticket_raised_table"],
        "expected_indicators": ["Agra", "unique_topic_id"],
    },
    {
        "id": "SC3_02",
        "scenario": 3,
        "title": "Flagged Profiles Frequency in Recurring Agitations",
        "query": "ऐसे कौन से सोशल मीडिया हैंडल्स हैं जो पिछले 3 महीनों में एक से अधिक बार भड़काऊ या विरोध से जुड़े मामलों में सामने आए हैं?",
        "intent": "Frequent actor analysis across distinct topic IDs",
        "expected_tables": ["analyzed_data", "post_users"],
        "expected_indicators": ["post_bank_author_username", "COUNT(DISTINCT"],
    },
    {
        "id": "SC3_03",
        "scenario": 3,
        "title": "Targeted Organizations & Entity Stance Analysis",
        "query": "Which government departments or police units were most frequently targeted with negative public reaction recently?",
        "intent": "Sentiment entity aggregation by organization with negative stance",
        "expected_tables": ["sentiment_entities", "analyzed_data"],
        "expected_indicators": ["ORGANIZATION", "NEGATIVE", "entity_name"],
    },

    # =========================================================================
    # 10 BENCHMARK VIRAL CASES / TOPICS
    # =========================================================================
    {
        "id": "TOPIC_01",
        "scenario": 4,
        "title": "Benchmark 1: UPSSSC Delay & Candidate Unrest",
        "query": "UPSSSC परीक्षा रिजल्ट में देरी को लेकर छात्रों के आक्रोश और सोशल मीडिया कैंपेन का क्या विवरण है?",
        "intent": "UPSSSC student agitation analysis",
        "expected_tables": ["topic", "analyzed_data"],
        "expected_indicators": ["UPSSSC", "रिजल्ट", "अभ्यर्थी"],
    },
    {
        "id": "TOPIC_02",
        "scenario": 4,
        "title": "Benchmark 2: UPSI Candidates & Recruitment Demands",
        "query": "यूपी एसआई भर्ती परीक्षा और मेडिकल/जॉइनिंग प्रक्रिया को लेकर अभ्यर्थियों की क्या मुख्य मांगें हैं?",
        "intent": "UPSI recruitment topic tracking",
        "expected_tables": ["topic", "analyzed_data"],
        "expected_indicators": ["UPSI", "दरोगा", "भर्ती"],
    },
    {
        "id": "TOPIC_03",
        "scenario": 4,
        "title": "Benchmark 3: DGP Appointment & UPSC Panel",
        "query": "उत्तर प्रदेश के नए डीजीपी चयन और यूपीएससी पैनल को लेकर क्या चर्चा और मीडिया कवरेज चल रही है?",
        "intent": "DGP appointment / UPSC panel discourse",
        "expected_tables": ["topic", "analyzed_data"],
        "expected_indicators": ["DGP", "UPSC", "नियुक्ति"],
    },
    {
        "id": "TOPIC_04",
        "scenario": 4,
        "title": "Benchmark 4: Sonbhadra Complaint & Police FIR Status",
        "query": "सोनभद्र जिले में दर्ज शिकायत और पुलिस द्वारा दर्ज की गई एफआईआर की स्थिति क्या है?",
        "intent": "Sonbhadra district FIR / ticket status",
        "expected_tables": ["topic", "ticket_raised_table", "district_internal_report"],
        "expected_indicators": ["Sonbhadra", "FIR", "ticket_raised_table"],
    },
    {
        "id": "TOPIC_05",
        "scenario": 4,
        "title": "Benchmark 5: Agra Police Criticism & Public Reaction",
        "query": "आगरा पुलिस के व्यवहार या कार्यशैली को लेकर सोशल मीडिया पर क्या आलोचना हो रही है?",
        "intent": "Agra police conduct sentiment assessment",
        "expected_tables": ["analyzed_data", "topic"],
        "expected_indicators": ["Agra", "पुलिस", "Negative"],
    },
    {
        "id": "TOPIC_06",
        "scenario": 4,
        "title": "Benchmark 6: Bahraich Passing Out Parade & Law and Order",
        "query": "बहराइच में पुलिस ट्रेनिंग स्कूल की पासिंग आउट परेड और उससे संबंधित खबरों का ब्योरा दें।",
        "intent": "Bahraich passing out parade event tracking",
        "expected_tables": ["topic", "analyzed_data"],
        "expected_indicators": ["Bahraich", "परेड", "पासिंग आउट"],
    },
    {
        "id": "TOPIC_07",
        "scenario": 4,
        "title": "Benchmark 7: UPSSSC Lekhpal Paper Leak Allegations",
        "query": "लेखपाल भर्ती परीक्षा में पेपर लीक या धांधली से जुड़े दावों और उन पर पुलिस कार्रवाई का क्या अपडेट है?",
        "intent": "UPSSSC Lekhpal paper leak investigation",
        "expected_tables": ["topic", "analyzed_data"],
        "expected_indicators": ["Lekhpal", "लेखपाल", "पेपर लीक"],
    },
    {
        "id": "TOPIC_08",
        "scenario": 4,
        "title": "Benchmark 8: UPSDMA Inauguration & Disaster Management",
        "query": "राज्य आपदा प्रबंधन प्राधिकरण (UPSDMA) के नए केंद्र के उद्घाटन और आपदा राहत संबंधी क्या जानकारी है?",
        "intent": "UPSDMA infrastructure / event overview",
        "expected_tables": ["topic", "analyzed_data"],
        "expected_indicators": ["UPSDMA", "आपदा प्रबंधन", "उद्घाटन"],
    },
    {
        "id": "TOPIC_09",
        "scenario": 4,
        "title": "Benchmark 9: Shahjahanpur Police News & Major Crackdown",
        "query": "शाहजहांपुर पुलिस द्वारा हाल ही में अपराधियों के खिलाफ की गई बड़ी कार्रवाई की क्या रिपोर्ट है?",
        "intent": "Shahjahanpur police enforcement action",
        "expected_tables": ["topic", "analyzed_data"],
        "expected_indicators": ["Shahjahanpur", "शाहजहांपुर", "पुलिस"],
    },
    {
        "id": "TOPIC_10",
        "scenario": 4,
        "title": "Benchmark 10: Agra Hanuman Ji Temple / Communal Incident",
        "query": "आगरा में हनुमान जी मंदिर पर अभद्रता और तनाव की घटना को लेकर क्या स्थिति है और सोशल मीडिया पर क्या ट्रेंड है?",
        "intent": "Agra temple communal controversy tracking",
        "expected_tables": ["topic", "analyzed_data", "sentiment_entities"],
        "expected_indicators": ["Agra", "हनुमान", "मंदिर", "तनाव"],
    }
]


class DiagnosticLogger:
    """Renders formatted node transitions and performance analytics."""

    @staticmethod
    def print_banner(text: str):
        border = "=" * 80
        print(f"\n{C_BOLD}{C_CYAN}{border}{C_RESET}")
        print(f"{C_BOLD}{C_CYAN}  {text}{C_RESET}")
        print(f"{C_BOLD}{C_CYAN}{border}{C_RESET}\n")

    @staticmethod
    def print_case_header(tc: Dict[str, Any], idx: int, total: int):
        print(f"\n{C_BOLD}{C_MAGENTA}[TEST {idx}/{total}] [{tc['id']}] {tc['title']}{C_RESET}")
        print(f"  {C_BLUE}• Query:{C_RESET} {tc['query']}")
        print(f"  {C_BLUE}• Intent:{C_RESET} {tc['intent']}")
        print(f"  {C_BLUE}• Expected Tables:{C_RESET} {', '.join(tc['expected_tables'])}")

    @staticmethod
    def log_node_step(node_name: str, details: Dict[str, Any]):
        print(f"    {C_YELLOW}→ [{node_name}]{C_RESET} {json.dumps(details, ensure_ascii=False)}")

    @staticmethod
    def print_sql(sql: str):
        if not sql:
            print(f"    {C_RED}✖ No SQL generated{C_RESET}")
            return
        clean_sql = " ".join(sql.strip().split())
        print(f"    {C_GREEN}✔ SQL ({len(clean_sql)} chars):{C_RESET} {clean_sql[:160]}...")

    @staticmethod
    def print_result_summary(status: str, latency: float, rows: int, answer: str):
        color = C_GREEN if status == "PASS" else (C_YELLOW if status == "WARN" else C_RED)
        print(f"  {C_BOLD}{color}[{status}]{C_RESET} Completed in {latency:.2f}s | Rows: {rows} | Answer Length: {len(answer)} chars")
        if answer:
            snippet = answer.strip().replace("\n", " ")[:200]
            print(f"  {C_BLUE}• Summary Snippet:{C_RESET} {snippet}...")


async def run_in_process_test(test_cases: List[Dict[str, Any]], interactive: bool = False) -> List[Dict[str, Any]]:
    """Runs test cases directly through LangGraph pipeline imported from ollamaagent2."""
    print(f"\n{C_BOLD}Loading LangGraph pipeline from ollamaagent2...{C_RESET}")
    try:
        from ollamaagent2 import graph
    except ImportError as e:
        print(f"{C_RED}Failed to import graph from ollamaagent2: {e}{C_RESET}")
        return []

    results = []
    messages = []
    session_log = []
    last_topic_ids = []

    for idx, tc in enumerate(test_cases, 1):
        if interactive and idx > 1:
            prompt = input(f"\n{C_BOLD}{C_YELLOW}▶ Press [Enter] for next query, [s] to skip, [q] to quit: {C_RESET}").strip().lower()
            if prompt == 'q':
                print(f"{C_CYAN}Stopped by user.{C_RESET}")
                break
            if prompt == 's':
                print(f"{C_YELLOW}Skipped test {tc['id']}{C_RESET}")
                continue

        DiagnosticLogger.print_case_header(tc, idx, len(test_cases))
        start_time = time.time()

        initial_state = {
            "query": tc["query"],
            "original_query": tc["query"],
            "query_manager_feedback": "",
            "query_manager_retry_count": 0,
            "is_query_correct": True,
            "messages": messages,
            "corrected_query": "",
            "rewrite_context": "",
            "expert_name": "",
            "selected_tables": [],
            "table_reason": "",
            "sql": "",
            "sql_matches": True,
            "sql_match_reason": "",
            "retry_count": 0,
            "content_index_hint": "",
            "content_index_retry_count": 0,
            "rows": [],
            "is_dashboard_query": False,
            "query_intent": "count",
            "validated_sql_context": "",
            "reasoning": "",
            "answer": "",
            "needs_clarification": False,
            "explain_request": False,
            "last_sql_context": session_log[-1].get("sql", "") if session_log else "",
            "session_log": session_log,
            "last_topic_ids": last_topic_ids,
            "resolved_topic_reference": "",
            "post_metadata": {},
            "answer_feedback": "",
            "answer_retry_count": 0,
            "pending_keyword_confirmation": None,
        }

        try:
            output_state = await graph.ainvoke(initial_state)
            latency = time.time() - start_time

            sql = output_state.get("sql", "")
            rows = output_state.get("rows") or []
            answer = output_state.get("answer", "")
            selected_tables = output_state.get("selected_tables") or []
            standalone = output_state.get("query", tc["query"])

            DiagnosticLogger.log_node_step("query_manager", {"standalone_query": standalone})
            DiagnosticLogger.log_node_step("table_selector", {"tables": selected_tables})
            DiagnosticLogger.print_sql(sql)

            # Verification Logic
            has_sql = bool(sql)
            has_answer = bool(answer)
            status = "PASS" if (has_sql or has_answer) else "FAIL"

            DiagnosticLogger.print_result_summary(status, latency, len(rows), answer)

            # Update session context
            if output_state.get("last_topic_ids"):
                last_topic_ids = output_state["last_topic_ids"]
            if sql:
                session_log.append({"query": tc["query"], "sql": sql, "rows": len(rows)})

            results.append({
                "id": tc["id"],
                "status": status,
                "latency": latency,
                "sql": sql,
                "rows_count": len(rows),
                "answer_length": len(answer),
            })

        except Exception as exc:
            latency = time.time() - start_time
            print(f"  {C_RED}✖ Execution Exception: {exc}{C_RESET}")
            results.append({
                "id": tc["id"],
                "status": "FAIL",
                "latency": latency,
                "error": str(exc),
            })

    return results


async def run_server_test(test_cases: List[Dict[str, Any]], server_url: str, interactive: bool = False) -> List[Dict[str, Any]]:
    """Runs test cases against the HTTP streaming endpoint of server.py."""
    import httpx

    print(f"\n{C_BOLD}Testing against server endpoint: {server_url}/api/chat{C_RESET}")
    results = []

    async with httpx.AsyncClient(timeout=180.0) as client:
        # Clear session before start
        try:
            await client.post(f"{server_url}/api/clear")
        except Exception:
            pass

        for idx, tc in enumerate(test_cases, 1):
            if interactive and idx > 1:
                prompt = input(f"\n{C_BOLD}{C_YELLOW}▶ Press [Enter] for next query, [s] to skip, [q] to quit: {C_RESET}").strip().lower()
                if prompt == 'q':
                    print(f"{C_CYAN}Stopped by user.{C_RESET}")
                    break
                if prompt == 's':
                    print(f"{C_YELLOW}Skipped test {tc['id']}{C_RESET}")
                    continue

            DiagnosticLogger.print_case_header(tc, idx, len(test_cases))
            start_time = time.time()

            payload = {"query": tc["query"], "limit": "50"}
            answer_chunks = []
            status = "PASS"

            try:
                async with client.stream("POST", f"{server_url}/api/chat", json=payload) as response:
                    if response.status_code != 200:
                        status = "FAIL"
                        print(f"  {C_RED}✖ HTTP Error {response.status_code}{C_RESET}")
                    else:
                        async for chunk in response.aiter_text():
                            answer_chunks.append(chunk)

                latency = time.time() - start_time
                full_answer = "".join(answer_chunks)
                if not full_answer:
                    status = "WARN"

                DiagnosticLogger.print_result_summary(status, latency, 0, full_answer)

                results.append({
                    "id": tc["id"],
                    "status": status,
                    "latency": latency,
                    "answer_length": len(full_answer),
                })
            except Exception as e:
                latency = time.time() - start_time
                print(f"  {C_RED}✖ Request Exception: {e}{C_RESET}")
                results.append({
                    "id": tc["id"],
                    "status": "FAIL",
                    "latency": latency,
                    "error": str(e),
                })

    return results


def print_final_report(results: List[Dict[str, Any]]):
    """Prints a consolidated execution matrix and scorecard."""
    total = len(results)
    if total == 0:
        return
    passed = sum(1 for r in results if r.get("status") == "PASS")
    warned = sum(1 for r in results if r.get("status") == "WARN")
    failed = sum(1 for r in results if r.get("status") == "FAIL")
    avg_latency = sum(r.get("latency", 0) for r in results) / total if total > 0 else 0

    DiagnosticLogger.print_banner("EXECUTION SCORECARD & PIPELINE HEALTH REPORT")
    print(f"  {C_BOLD}Total Queries Executed:{C_RESET} {total}")
    print(f"  {C_GREEN}Passed:{C_RESET} {passed}")
    print(f"  {C_YELLOW}Warnings:{C_RESET} {warned}")
    print(f"  {C_RED}Failed:{C_RESET} {failed}")
    print(f"  {C_CYAN}Average Latency:{C_RESET} {avg_latency:.2f}s per query\n")

    print(f"{'ID':<10} | {'Status':<8} | {'Latency':<9} | {'Rows':<6} | {'Details'}")
    print("-" * 75)
    for r in results:
        status_col = (
            f"{C_GREEN}PASS{C_RESET}" if r.get("status") == "PASS"
            else (f"{C_YELLOW}WARN{C_RESET}" if r.get("status") == "WARN" else f"{C_RED}FAIL{C_RESET}")
        )
        print(f"{r.get('id', ''):<10} | {status_col:<17} | {r.get('latency', 0):.2f}s     | {r.get('rows_count', '-'):<6} | Ans Len: {r.get('answer_length', 0)}")
    print("-" * 75)


def list_all_queries():
    """Prints all available test queries with their ID, index, and query text."""
    DiagnosticLogger.print_banner("AVAILABLE TEST QUERIES & BENCHMARKS")
    print(f"{'Idx':<4} | {'ID':<10} | {'Scenario':<10} | {'Title & Query'}")
    print("-" * 80)
    for idx, tc in enumerate(TEST_SCENARIOS, 1):
        sc_label = f"Scenario {tc['scenario']}" if tc['scenario'] <= 3 else "Benchmark"
        print(f"{idx:<4} | {tc['id']:<10} | {sc_label:<10} | {C_BOLD}{tc['title']}{C_RESET}")
        print(f"{'':<4}   {'':<10}   {'':<10}   {C_BLUE}↳ \"{tc['query']}\"{C_RESET}\n")
    print("-" * 80)
    print(f"{C_GREEN}To run any single query by index: {C_BOLD}python3 test_pipeline_scenarios.py --index <N>{C_RESET}")
    print(f"{C_GREEN}To run any single query by ID:    {C_BOLD}python3 test_pipeline_scenarios.py --id <ID>{C_RESET}")
    print(f"{C_GREEN}To step through one-by-one:       {C_BOLD}python3 test_pipeline_scenarios.py --step{C_RESET}\n")


def main():
    parser = argparse.ArgumentParser(description="Matrix Pipeline Scenario & Benchmark Test Harness")
    parser.add_argument("--mode", choices=["in-process", "server"], default="in-process", help="Execution mode")
    parser.add_argument("--url", default="http://127.0.0.1:8123", help="Server URL for server mode")
    parser.add_argument("--filter", default=None, help="Filter test cases by keyword")
    parser.add_argument("--scenario", type=int, default=None, help="Filter by scenario number (1, 2, 3, or 4 for benchmarks)")
    parser.add_argument("--id", default=None, help="Run a specific test case by ID (e.g. TOPIC_01, SC1_01)")
    parser.add_argument("--index", type=int, default=None, help="Run a specific test case by index (1 to 21)")
    parser.add_argument("--query", "-q", default=None, help="Run a custom ad-hoc query string directly")
    parser.add_argument("--step", "-i", "--interactive", action="store_true", help="Step-by-step interactive mode (pause after each query)")
    parser.add_argument("--list", "-l", action="store_true", help="List all available benchmark and scenario queries")
    args = parser.parse_args()

    if args.list:
        list_all_queries()
        return

    if args.query:
        filtered_cases = [{
            "id": "CUSTOM",
            "scenario": 0,
            "title": "Custom Ad-hoc Query",
            "query": args.query,
            "intent": "Ad-hoc user query execution",
            "expected_tables": [],
            "expected_indicators": [],
        }]
    elif args.id:
        filtered_cases = [tc for tc in TEST_SCENARIOS if tc["id"].upper() == args.id.upper()]
        if not filtered_cases:
            print(f"{C_RED}No test case found with ID '{args.id}'. Use --list to see available IDs.{C_RESET}")
            return
    elif args.index is not None:
        if 1 <= args.index <= len(TEST_SCENARIOS):
            filtered_cases = [TEST_SCENARIOS[args.index - 1]]
        else:
            print(f"{C_RED}Invalid index {args.index}. Must be between 1 and {len(TEST_SCENARIOS)}. Use --list to see all.{C_RESET}")
            return
    else:
        filtered_cases = TEST_SCENARIOS
        if args.scenario:
            filtered_cases = [tc for tc in filtered_cases if tc.get("scenario") == args.scenario]
        if args.filter:
            kw = args.filter.lower()
            filtered_cases = [tc for tc in filtered_cases if kw in tc["title"].lower() or kw in tc["query"].lower()]

    if not filtered_cases:
        print(f"{C_RED}No test cases match filter!{C_RESET}")
        return

    DiagnosticLogger.print_banner(f"STARTING MATRIX APP TEST HARNESS (Mode: {args.mode.upper()}, Tests: {len(filtered_cases)})")

    if args.mode == "in-process":
        results = asyncio.run(run_in_process_test(filtered_cases, interactive=args.step))
    else:
        results = asyncio.run(run_server_test(filtered_cases, args.url, interactive=args.step))

    print_final_report(results)


if __name__ == "__main__":
    main()

