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
                # Determine table schemas based on mappings
                conformed_columns = []
                for m in mappings:
                    col_name = m.get("target_attribute")
                    rule = m.get("transform_rule", "").upper()
                    
                    # Convert Spark types to PostgreSQL types
                    db_type = "VARCHAR(255)"
                    if "DECIMAL" in rule:
                        db_type = "NUMERIC(18,2)"
                    elif "INT" in rule:
                        db_type = "INTEGER"
                    elif "DATE" in rule and "TIME" not in rule:
                        db_type = "DATE"
                    elif "TIMESTAMP" in rule:
                        db_type = "TIMESTAMP"
                    conformed_columns.append(f"{col_name} {db_type}")

                # Append metadata columns
                conformed_columns.append("_ingested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
                conformed_columns.append("_source_file VARCHAR(512)")

                # Create Bronze & Silver tables
                bronze_table = f"bronze_{entity_name}"
                silver_table = f"silver_{entity_name}"

                logger.info(f"Recreating table {bronze_table}...")
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
                        target_col = m.get("target_attribute")
                        rule = m.get("transform_rule", "")

                        val = rec.get(src_col)

                        # Apply transformation rule conversions
                        if "HASH" in rule.upper() or "SHA" in rule.upper():
                            if val is not None:
                                transformed_rec[target_col] = hashlib.sha256(str(val).encode('utf-8')).hexdigest()
                            else:
                                transformed_rec[target_col] = None
                        elif "DECIMAL" in rule.upper() or "DOUBLE" in rule.upper():
                            transformed_rec[target_col] = float(val) if val is not None else None
                        elif "INT" in rule.upper():
                            transformed_rec[target_col] = int(val) if val is not None else None
                        else:
                            transformed_rec[target_col] = str(val) if val is not None else None

                    # Insert to Bronze (Raw values mapped)
                    cols = list(transformed_rec.keys()) + ["_source_file"]
                    vals = list(transformed_rec.values()) + [f"s3://{bucket}/{key}"]
                    
                    placeholders = ", ".join(["%s"] * len(vals))
                    cur.execute(
                        f"INSERT INTO {bronze_table} ({', '.join(cols)}) VALUES ({placeholders})",
                        vals
                    )

                    # Insert to Silver (Conformed)
                    cur.execute(
                        f"INSERT INTO {silver_table} ({', '.join(cols)}) VALUES ({placeholders})",
                        vals
                    )
                    inserted_count += 1

                conn.commit()
                logger.info(f"Ingested and conformed {inserted_count} records into {silver_table}")
                return {"status": "SUCCESS", "records_processed": inserted_count, "silver_table": silver_table}
