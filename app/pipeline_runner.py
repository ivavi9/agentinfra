import json
import logging
import hashlib
import boto3
import psycopg

from typing import Optional, Dict, Any

from mcp_client import MCPS3ClientAdapter

logger = logging.getLogger("agent-core.pipeline_runner")


class PipelineRunner:
    def __init__(self, db_config: dict):
        self.db_config = db_config
        # Standard boto3 client resolves EKS SA OIDC IRSA keylessly
        self.s3_client = boto3.client("s3")
        self.mcp_client = MCPS3ClientAdapter()

    def discover_landing_bucket(self) -> str:
        """Discovers landing bucket dynamically via MCP S3 Server."""
        try:
            return self.mcp_client.discover_landing_bucket()
        except Exception as e:
            logger.warning(f"MCP bucket discovery fallback to boto3: {e}")
            buckets = self.s3_client.list_buckets()
            for b in buckets.get("Buckets", []):
                name = b["Name"]
                if name.startswith("agent-infra-landing-bucket-"):
                    return name
            raise FileNotFoundError(
                "No bucket found matching prefix 'agent-infra-landing-bucket-'"
            )

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
        """Downloads and parses JSON/JSONL raw data records from S3 via MCP tool."""
        logger.info(f"Downloading s3://{bucket}/{key} via MCP S3 Server")
        try:
            return self.mcp_client.read_json_records(bucket, key)
        except Exception as e:
            logger.warning(f"MCP S3 read failed, fallback to direct boto3: {e}")
            response = self.s3_client.get_object(Bucket=bucket, Key=key)
            content = response["Body"].read().decode("utf-8")
            records = []
            for line in content.split("\n"):
                if line.strip():
                    records.append(json.loads(line.strip()))
            return records

    def run_conformance(
        self,
        entity_name: str,
        mappings: list,
        bucket: Optional[str] = None,
        tenant_id: Optional[str] = None,
    ) -> dict:
        """Ingests raw S3 assets, performs column transformations, and writes conformed tables to PostgreSQL."""
        if not bucket:
            bucket = self.discover_landing_bucket()
        # 1. Download raw data with tenant path partitioning fallback
        prefix = f"{tenant_id}/raw/{entity_name}" if tenant_id else f"raw/{entity_name}"
        key = f"{prefix}/{entity_name}.json"
        try:
            raw_records = self.download_s3_json(bucket, key)
        except Exception:
            # Fallback to default unpartitioned path
            raw_records = self.download_s3_json(
                bucket, f"raw/{entity_name}/{entity_name}.json"
            )

        logger.info(f"Loaded {len(raw_records)} raw records for entity: {entity_name}")

        bronze_table = (
            f"bronze_{tenant_id}_{entity_name}"
            if tenant_id
            else f"bronze_{entity_name}"
        )
        silver_table = (
            f"silver_{tenant_id}_{entity_name}"
            if tenant_id
            else f"silver_{entity_name}"
        )

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
                    rule = (
                        m.get("transform_rule") or m.get("transformation_rule") or ""
                    ).upper()

                    # Convert Spark/SQL types to PostgreSQL types
                    db_type = "VARCHAR(255)"
                    if "DECIMAL" in rule or "NUMERIC" in rule:
                        db_type = "NUMERIC(18,2)"
                    elif "INT" in rule:
                        db_type = "INTEGER"
                    elif ("DATE" in rule and "TIME" not in rule) or "TO_DATE" in rule:
                        db_type = "DATE"
                    elif (
                        "TIMESTAMP" in rule
                        or "CURRENT_TIMESTAMP" in rule
                        or "current_timestamp" in m.get("transform_rule", "")
                    ):
                        db_type = "TIMESTAMP"

                    key_lower = col_name.lower()
                    if key_lower not in seen_cols:
                        seen_cols[key_lower] = (col_name, db_type)

                # Append standard metadata columns only if not already produced by LLM mappings
                if "_ingested_at" not in seen_cols:
                    seen_cols["_ingested_at"] = (
                        "_ingested_at",
                        "TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
                    )
                if "_source_file" not in seen_cols:
                    seen_cols["_source_file"] = ("_source_file", "VARCHAR(512)")

                conformed_columns = [
                    f"{col} {dtype}" for col, dtype in seen_cols.values()
                ]

                quarantine_table = (
                    f"quarantine_{tenant_id}_{entity_name}"
                    if tenant_id
                    else f"quarantine_{entity_name}"
                )

                # Find primary surrogate key column for Silver MERGE upserts
                pk_col = None
                for m in mappings:
                    target_col = (
                        m.get("target_attribute") or m.get("target_column") or ""
                    ).strip()
                    if target_col and (
                        m.get("is_surrogate_key") or m.get("is_primary_key")
                    ):
                        pk_col = target_col
                        break

                if not pk_col:
                    for col_key, (col_name, _) in seen_cols.items():
                        if "id" in col_key or "pk" in col_key:
                            pk_col = col_name
                            break
                if not pk_col:
                    pk_col = list(seen_cols.values())[0][0]

                # Check existing DB schema for Silver table's actual PK to prevent ON CONFLICT constraint mismatch
                try:
                    cur.execute(
                        """
                        SELECT kcu.column_name
                        FROM information_schema.table_constraints tc
                        JOIN information_schema.key_column_usage kcu
                          ON tc.constraint_name = kcu.constraint_name
                         AND tc.table_schema = kcu.table_schema
                        WHERE tc.constraint_type = 'PRIMARY KEY'
                          AND tc.table_name = %s
                        LIMIT 1
                    """,
                        (silver_table,),
                    )
                    existing_pk_row = cur.fetchone()
                    if existing_pk_row and isinstance(existing_pk_row[0], str):
                        pk_col = existing_pk_row[0]
                except Exception as ex_pk:
                    logger.warning(
                        f"Could not inspect existing PK constraint for {silver_table}: {ex_pk}"
                    )

                logger.info(f"Ensuring Bronze append-only table {bronze_table}...")
                cur.execute(
                    f"CREATE TABLE IF NOT EXISTS {bronze_table} ({', '.join(conformed_columns)})"
                )

                logger.info(
                    f"Ensuring Silver upsert table {silver_table} with PK ({pk_col})..."
                )
                silver_cols_def = []
                for col_name, dtype in seen_cols.values():
                    if col_name == pk_col:
                        silver_cols_def.append(f"{col_name} {dtype} PRIMARY KEY")
                    else:
                        silver_cols_def.append(f"{col_name} {dtype}")

                # Re-create or ensure silver table with PK
                cur.execute(
                    f"CREATE TABLE IF NOT EXISTS {silver_table} ({', '.join(silver_cols_def)})"
                )
                cur.execute(
                    f"CREATE TABLE IF NOT EXISTS {quarantine_table} ({', '.join(conformed_columns)}, _rejection_reason VARCHAR(255))"
                )

                inserted_count = 0
                quarantined_count = 0

                for rec in raw_records:
                    transformed_rec: Dict[str, Any] = {}
                    for m in mappings:
                        src_col = m.get("source_column")
                        target_col = (
                            m.get("target_attribute") or m.get("target_column") or ""
                        ).strip()
                        if not target_col:
                            continue
                        rule = (
                            m.get("transform_rule")
                            or m.get("transformation_rule")
                            or ""
                        )
                        val = rec.get(src_col)

                        # Apply transformation rule conversions
                        if "HASH" in rule.upper() or "SHA" in rule.upper():
                            transformed_rec[target_col] = (
                                hashlib.sha256(str(val).encode("utf-8")).hexdigest()
                                if val is not None
                                else None
                            )
                        elif (
                            "DECIMAL" in rule.upper()
                            or "DOUBLE" in rule.upper()
                            or "NUMERIC" in rule.upper()
                        ):
                            transformed_rec[target_col] = (
                                float(val) if val is not None else None
                            )
                        elif "INT" in rule.upper():
                            transformed_rec[target_col] = (
                                int(val) if val is not None else None
                            )
                        elif (
                            "CURRENT_TIMESTAMP" in rule.upper()
                            or "current_timestamp" in rule
                        ):
                            transformed_rec[target_col] = None  # DB default
                        elif rule.startswith("lit("):
                            transformed_rec[target_col] = rule[4:-1].strip("'\"")
                        else:
                            transformed_rec[target_col] = (
                                str(val) if val is not None else None
                            )

                    filtered_rec = {
                        k: v
                        for k, v in transformed_rec.items()
                        if k.lower() in seen_cols
                    }
                    filtered_rec["_source_file"] = f"s3://{bucket}/{key}"

                    cols = list(filtered_rec.keys())
                    vals = list(filtered_rec.values())
                    placeholders = ", ".join(["%s"] * len(vals))

                    # 1. Bronze: Raw Append-Only Ingestion
                    cur.execute(
                        f"INSERT INTO {bronze_table} ({', '.join(cols)}) VALUES ({placeholders})",
                        vals,
                    )

                    # 2. Data Quality Gate Check
                    rejection_reason = None
                    pk_val = next(
                        (
                            v
                            for k, v in filtered_rec.items()
                            if k.lower() == pk_col.lower()
                        ),
                        None,
                    )
                    if pk_val is None or str(pk_val).strip() == "":
                        rejection_reason = "NULL_PRIMARY_KEY"

                    if rejection_reason:
                        # Quarantine row
                        quarantine_cols = cols + ["_rejection_reason"]
                        quarantine_vals = vals + [rejection_reason]
                        q_placeholders = ", ".join(["%s"] * len(quarantine_vals))
                        cur.execute(
                            f"INSERT INTO {quarantine_table} ({', '.join(quarantine_cols)}) VALUES ({q_placeholders})",
                            quarantine_vals,
                        )
                        quarantined_count += 1
                    else:
                        # 3. Silver: Idempotent MERGE / Upsert on Primary Key
                        non_pk_cols = [c for c in cols if c != pk_col]
                        if non_pk_cols:
                            update_stmt = ", ".join(
                                [f"{c} = EXCLUDED.{c}" for c in non_pk_cols]
                            )
                            upsert_sql = f"""
                                INSERT INTO {silver_table} ({', '.join(cols)}) 
                                VALUES ({placeholders})
                                ON CONFLICT ({pk_col}) DO UPDATE SET {update_stmt}
                            """
                        else:
                            upsert_sql = f"""
                                INSERT INTO {silver_table} ({', '.join(cols)}) 
                                VALUES ({placeholders})
                                ON CONFLICT ({pk_col}) DO NOTHING
                            """
                        cur.execute(upsert_sql, vals)
                        inserted_count += 1

                conn.commit()
                logger.info(
                    f"Ingested {inserted_count} conformed records into {silver_table}, quarantined {quarantined_count} records."
                )
                return {
                    "status": "SUCCESS",
                    "records_processed": inserted_count,
                    "records_quarantined": quarantined_count,
                    "silver_table": silver_table,
                    "quarantine_table": quarantine_table,
                }
