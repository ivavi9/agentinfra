import os
import sys
import unittest
from unittest.mock import MagicMock

# Add app directory to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../app')))

from agents.supervisor import DatabricksPipelineGraph

class TestPipelineCompilation(unittest.TestCase):
    def test_end_to_end_pipeline_generation(self):
        # Instantiate graph with a mocked database config (None to fallback to MemorySaver checkpointer)
        graph_orchestrator = DatabricksPipelineGraph(api_key="mock_key", db_config=None)

        # Mock each agent's run/analyse methods to avoid calling the LLM
        graph_orchestrator.ba_analyst.analyze_brd = MagicMock(return_value={
            "value_streams": [
                {
                    "name": "Transaction Ingest",
                    "entities": [
                        {"name": "Customer", "attributes": ["customer_id", "name"], "primary_key": "customer_id"},
                        {"name": "Transaction", "attributes": ["txn_id", "amount"], "primary_key": "txn_id"}
                    ],
                    "estimated_volume_per_day": 100000,
                    "sla_latency": "hourly",
                    "source_system": "CORE_DB"
                }
            ]
        })

        graph_orchestrator.data_profiler.profile_schema = MagicMock(return_value={
            "bronze_tables": [
                {
                    "table_name": "bronze_customer",
                    "columns": [
                        {"name": "customer_id", "type": "STRING", "nullable": False},
                        {"name": "name", "type": "STRING", "nullable": True}
                    ],
                    "primary_key": "customer_id"
                }
            ]
        })

        graph_orchestrator.silver_model.conform_model = MagicMock(return_value={
            "silver_conformed_tables": [
                {
                    "source_table": "bronze_customer",
                    "subject_area": "INVOLVED_PARTY",
                    "target_table": "INDIVIDUAL",
                    "attributes": [
                        {"source_column": "customer_id", "target_attribute": "IP_ID"},
                        {"source_column": "name", "target_attribute": "IP_NM"}
                    ]
                }
            ]
        })

        graph_orchestrator.stm_mapping.generate_mapping = MagicMock(return_value={
            "mappings": [
                {
                    "source_table": "bronze_customer",
                    "source_column": "customer_id",
                    "target_table": "individual",
                    "target_column": "ip_id",
                    "transformation_rule": "cast(src.customer_id as string)",
                    "is_surrogate_key": True
                }
            ]
        })

        graph_orchestrator.dab_generator.generate_bundle = MagicMock(return_value={
            "bundle_name": "mock_bundle",
            "files": {
                "databricks.yml": "bundle:\n  name: mock_bundle",
                "resources/pipelines.yml": "pipelines:\n  mock_pipeline: {}",
                "src/conformance.py": "print('conformed')"
            }
        })

        # Run Phase 1: Analyse BRD up to human-in-the-loop interrupt
        thread_id = "test_thread"
        config = {"configurable": {"thread_id": thread_id}}
        
        # Initial state setup
        graph_orchestrator.graph.update_state(config, {
            "brd_document": "Value Stream specs here...",
            "value_stream_json": {},
            "bronze_schema": {},
            "silver_conformed": {},
            "mapping_matrix": [],
            "approved": False,
            "generated_bundle_files": {},
            "error": None
        })

        # Invoke graph. It should run ba_analyst -> profiler -> conformer -> mapper -> and pause (interrupted before dab_generator)
        result = graph_orchestrator.graph.invoke(None, config=config)

        # Assertions for Phase 1 (up to mapping generation)
        self.assertIn("Transaction Ingest", str(result["value_stream_json"]))
        self.assertIn("bronze_customer", str(result["bronze_schema"]))
        self.assertIn("INVOLVED_PARTY", str(result["silver_conformed"]))
        self.assertEqual(len(result["mapping_matrix"]), 1)
        self.assertFalse(result["approved"])
        self.assertEqual(result["generated_bundle_files"], {})

        # Verify that graph is indeed interrupted at dab_generator node
        state = graph_orchestrator.graph.get_state(config)
        self.assertEqual(list(state.next), ["dab_generator"])

        # Phase 2: Resume with approved = True
        graph_orchestrator.graph.update_state(config, {
            "mapping_matrix": result["mapping_matrix"],
            "approved": True
        })

        # Run again to resume from interrupt
        resume_result = graph_orchestrator.graph.invoke(None, config=config)

        # Assertions for Phase 2 (post-approval compilation)
        self.assertTrue(resume_result["approved"])
        self.assertIn("databricks.yml", resume_result["generated_bundle_files"])
        self.assertIn("resources/pipelines.yml", resume_result["generated_bundle_files"])
        self.assertIn("src/conformance.py", resume_result["generated_bundle_files"])
        self.assertEqual(resume_result["generated_bundle_files"]["databricks.yml"], "bundle:\n  name: mock_bundle")

        print("✅ Local unit test for DatabricksPipelineGraph passed successfully!")

if __name__ == "__main__":
    unittest.main()
