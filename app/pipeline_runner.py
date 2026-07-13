import os
import json
import logging
from datetime import datetime
import hashlib
import boto3
import psycopg

logger = logging.getLogger("agent-core.pipeline_runner")

class PipelineRunner:
    def __init__(self, db_config: dict):
        self.db_config = db_config
        # Standard boto3 client resolves EKS SA OIDC IRSA keylessly
        self.s3_client = boto3.client("s3")

    def discover_landing_bucket(self) -> str:
        """Discovers the landing bucket dynamically by listing buckets matching prefix."""
        try:
            buckets = self.s3_client.list_buckets()
            for b in buckets.get("Buckets", []):
                name = b["Name"]
                if name.startswith("agent-infra-landing-bucket-"):
                    logger.info(f"Discovered landing bucket: {name}")
                    return name
            raise FileNotFoundError("No bucket found matching prefix 'agent-infra-landing-bucket-'")
        except Exception as e:
            logger.error(f"Failed to discover landing bucket: {str(e)}")
            raise e

    def _get_connection(self):
        conn_info = (
            f"host={self.db_config.get('db_host')} "
            f"port={self.db_config.get('db_port', '5432')} "
            f"dbname={self.db_config.get('db_name')} "
            f"user={self.db_config.get('db_user')} "
            f"password={self.db_config.get('db_password')}"
        )
        return psycopg.connect(conn_info)

    def download_s3_json(self, bucket: str, key: str) -> list:
        """Downloads a JSON Lines file from S3 and parses it into records."""
        logger.info(f"Downloading s3://{bucket}/{key}")
        try:
            response = self.s3_client.get_object(Bucket=bucket, Key=key)
            content = response["Body"].read().decode("utf-8")
            records = []
            for line in content.split("\n"):
                if line.strip():
                    records.append(json.loads(line.strip()))
            return records
        except Exception as e:
            logger.error(f"Failed to download or parse s3://{bucket}/{key}: {str(e)}")
            raise e

    def run_conformance(self, entity_name: str, mappings: list, bucket: str = None) -> dict:
        """Ingests raw S3 assets, performs column transformations, and writes conformed tables to PostgreSQL."""
        if not bucket:
            bucket = self.discover_landing_bucket()
        # 1. Download raw data
        key = f"raw/{entity_name}/{entity_name}.json"
        raw_records = self.download_s3_json(bucket, key)
        logger.info(f"Loaded {len(raw_records)} raw records for entity: {entity_name}")

        # 2. Establish database connection
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                # Determine table schemas based on mappings — deduplicate target columns
                seen_cols = {}  # col_name_lower -> (col_name, db_type)
                for m in mappings:
                    # Support both field names from analyse (target_column) and approve (target_attribute)
                    col_name = (
                        m.get("target_attribute") or m.get("target_column") or ""
                    ).strip()
                    if not col_name:
                        continue
                    rule = (m.get("transform_rule") or m.get("transformation_rule") or "").upper()

                    # Convert Spark/SQL types to PostgreSQL types
                    db_type = "VARCHAR(255)"
                    if "DECIMAL" in rule or "NUMERIC" in rule:
                        db_type = "NUMERIC(18,2)"
                    elif "INT" in rule:
                        db_type = "INTEGER"
                    elif ("DATE" in rule and "TIME" not in rule) or "TO_DATE" in rule:
                        db_type = "DATE"
                    elif "TIMESTAMP" in rule or "CURRENT_TIMESTAMP" in rule or "current_timestamp" in m.get("transform_rule", ""):
                        db_type = "TIMESTAMP"

                    key_lower = col_name.lower()
                    if key_lower not in seen_cols:
                        seen_cols[key_lower] = (col_name, db_type)

                # Append standard metadata columns only if not already produced by LLM mappings
                if "_ingested_at" not in seen_cols:
                    seen_cols["_ingested_at"] = ("_ingested_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
                if "_source_file" not in seen_cols:
                    seen_cols["_source_file"] = ("_source_file", "VARCHAR(512)")

                conformed_columns = [f"{col} {dtype}" for col, dtype in seen_cols.values()]

                # Create Bronze & Silver tables
                bronze_table = f"bronze_{entity_name}"
                silver_table = f"silver_{entity_name}"

                logger.info(f"Recreating table {bronze_table} with columns: {list(seen_cols.keys())}")
                cur.execute(f"DROP TABLE IF EXISTS {bronze_table} CASCADE")
                cur.execute(f"CREATE TABLE {bronze_table} ({', '.join(conformed_columns)})")

                logger.info(f"Recreating table {silver_table}...")
                cur.execute(f"DROP TABLE IF EXISTS {silver_table} CASCADE")
                cur.execute(f"CREATE TABLE {silver_table} ({', '.join(conformed_columns)})")

                # Insert transformed records
                inserted_count = 0
                for rec in raw_records:
                    transformed_rec = {}
                    for m in mappings:
                        src_col = m.get("source_column")
                        # Support both target_attribute (approve payload) and target_column (analyse response)
                        target_col = (
                            m.get("target_attribute")
                            or m.get("target_column")
                            or ""
                        ).strip()
                        if not target_col:
                            continue  # skip unmapped rows
                        rule = m.get("transform_rule") or m.get("transformation_rule") or ""

                        val = rec.get(src_col)

                        # Apply transformation rule conversions
                        if "HASH" in rule.upper() or "SHA" in rule.upper():
                            transformed_rec[target_col] = hashlib.sha256(str(val).encode('utf-8')).hexdigest() if val is not None else None
                        elif "DECIMAL" in rule.upper() or "DOUBLE" in rule.upper() or "NUMERIC" in rule.upper():
                            transformed_rec[target_col] = float(val) if val is not None else None
                        elif "INT" in rule.upper():
                            transformed_rec[target_col] = int(val) if val is not None else None
                        elif "CURRENT_TIMESTAMP" in rule.upper() or "current_timestamp" in rule:
                            transformed_rec[target_col] = None  # DB default handles this
                        elif rule.startswith("lit("):
                            # Spark lit() literal — extract string value
                            transformed_rec[target_col] = rule[4:-1].strip("'\"")
                        else:
                            transformed_rec[target_col] = str(val) if val is not None else None

                    # Only include columns that exist in the schema (seen_cols)
                    filtered_rec = {
                        k: v for k, v in transformed_rec.items()
                        if k.lower() in seen_cols
                    }
                    filtered_rec["_source_file"] = f"s3://{bucket}/{key}"

                    cols = list(filtered_rec.keys())
                    vals = list(filtered_rec.values())

                    placeholders = ", ".join(["%s"] * len(vals))
                    cur.execute(
                        f"INSERT INTO {bronze_table} ({', '.join(cols)}) VALUES ({placeholders})",
                        vals
                    )
                    cur.execute(
                        f"INSERT INTO {silver_table} ({', '.join(cols)}) VALUES ({placeholders})",
                        vals
                    )
                    inserted_count += 1

                conn.commit()
                logger.info(f"Ingested and conformed {inserted_count} records into {silver_table}")
                return {"status": "SUCCESS", "records_processed": inserted_count, "silver_table": silver_table}

