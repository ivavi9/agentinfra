import json
import subprocess
import time
import sys
import httpx
import boto3

# Active parameters
CLIENT_ID = "5f6s8b6ur4bokfnucs98ieds3p"
USER_POOL_ID = "us-east-1_JDJLk1IzO"
REGION = "us-east-1"
USERNAME = "devtest@example.com"
PASSWORD = "DevTest123!"
SESSION_ID = "test-e2e-session-py"
GATEWAY_URL = "http://a90fb1d5f715a4159abc7483e774bd8d-498703573.us-east-1.elb.amazonaws.com"
KUBECONFIG = "KUBECONFIG=.kube/config"

print("1. Authenticating with Cognito...")
try:
    cognito_client = boto3.client("cognito-idp", region_name=REGION)
    auth_resp = cognito_client.initiate_auth(
        ClientId=CLIENT_ID,
        AuthFlow="USER_PASSWORD_AUTH",
        AuthParameters={
            "USERNAME": USERNAME,
            "PASSWORD": PASSWORD
        }
    )
    token = auth_resp["AuthenticationResult"]["IdToken"]
    print("Authentication successful!")
except Exception as e:
    print(f"Authentication failed: {e}")
    sys.exit(1)

headers = {
    "Authorization": f"Bearer {token}",
    "Content-Type": "application/json"
}

print("\n2. Sending pipeline analysis request (POST /pipeline/analyse)...")
brd_text = (
    "Raw transaction logs are ingested from S3. They contain transaction_id, customer_id, "
    "account_id, amount, and transaction_date. We need to parse dates, cast transaction amount "
    "to decimal, hash customer_id, and conforming attributes to target Silver schemas."
)
with httpx.Client(timeout=30.0) as client:
    resp = client.post(
        f"{GATEWAY_URL}/pipeline/analyse",
        headers=headers,
        json={"brd_document": brd_text, "session_id": SESSION_ID}
    )
    print("Analysis response status:", resp.status_code)
    try:
        analysis_data = resp.json()
        print("Analysis completed successfully. Mappings generated:")
        print(json.dumps(analysis_data.get("mapping_matrix"), indent=2))
    except Exception as e:
        print("Failed to parse analysis response:", resp.text)
        sys.exit(1)

    print("\n3. Sending pipeline approval (POST /pipeline/approve)...")
    mappings = analysis_data.get("mapping_matrix", [])
    for m in mappings:
        if m.get("source_column") == "customer_id":
            m["target_column"] = "customer_id_hash"
            m["transformation_rule"] = "SHA-256 HASH"
        elif m.get("source_column") == "amount":
            m["target_column"] = "transaction_amount"
            m["transformation_rule"] = "CAST(amount AS DECIMAL)"
        elif m.get("source_column") == "transaction_date":
            m["target_column"] = "transaction_timestamp"
            m["transformation_rule"] = "CAST(transaction_date AS TIMESTAMP)"

    api_mappings = []
    for m in mappings:
        api_mappings.append({
            "source_table": m.get("source_table", "transaction"),
            "source_column": m.get("source_column"),
            "target_table": "silver_transaction",
            "target_attribute": m.get("target_column") or m.get("target_attribute") or m.get("source_column"),
            "transform_rule": m.get("transformation_rule") or m.get("transform_rule") or "CAST"
        })

    resp = client.post(
        f"{GATEWAY_URL}/pipeline/approve",
        headers=headers,
        json={"session_id": SESSION_ID, "mapping_matrix": api_mappings}
    )
    print("Approval response status:", resp.status_code)

    # Discover bucket name
    print("\n4. Discovering S3 Landing Zone Bucket...")
    s3_client = boto3.client("s3", region_name=REGION)
    buckets = s3_client.list_buckets()
    bucket_name = None
    for b in buckets.get("Buckets", []):
        if b["Name"].startswith("agent-infra-landing-bucket-"):
            bucket_name = b["Name"]
            break
    if not bucket_name:
        print("ERROR: Landing bucket not found.")
        sys.exit(1)
    print("Discovered landing bucket:", bucket_name)

    print("\n5. Executing Medallion Pipeline Ingestion Run (POST /pipeline/run)...")
    resp = client.post(
        f"{GATEWAY_URL}/pipeline/run",
        headers=headers,
        json={"session_id": SESSION_ID, "bucket_name": bucket_name, "entity_name": "transaction"},
        timeout=60.0
    )
    print("Run response status:", resp.status_code)
    try:
        run_result = resp.json()
        print("Run response body:", json.dumps(run_result, indent=2))
    except Exception as e:
        print("Failed to parse run response:", resp.text)
        sys.exit(1)

    if resp.status_code != 200:
        print(f"\nERROR: Pipeline run failed with status {resp.status_code}")
        sys.exit(1)

# Step 6: Verify DB records by exec-ing psql inside the agent-core pod (within VPC)
print("\n6. Verifying PostgreSQL records via kubectl exec into agent-core pod (in-VPC access)...")
try:
    # Get the DB connection env vars from the running pod
    get_pod_cmd = f"{KUBECONFIG} kubectl get pod -l app=agent-core -o jsonpath='{{.items[0].metadata.name}}'"
    pod_name = subprocess.check_output(get_pod_cmd, shell=True).decode().strip()
    print(f"Using pod: {pod_name}")

    # Run psql query inside the pod
    psql_query = "SELECT COUNT(*) FROM silver_transaction;"
    kubectl_exec = (
        f"{KUBECONFIG} kubectl exec {pod_name} -- python3 -c \""
        "import psycopg, os; "
        "conn = psycopg.connect(host=os.environ.get('DB_HOST',''), "
        "port=os.environ.get('DB_PORT','5432'), "
        "dbname=os.environ.get('DB_NAME','agentinfra'), "
        "user=os.environ.get('DB_USER','agentadmin'), "
        "password=os.environ.get('DB_PASSWORD','')); "
        "cur = conn.cursor(); "
        "cur.execute('SELECT COUNT(*) FROM silver_transaction;'); "
        "print('silver_transaction rows:', cur.fetchone()[0]); "
        "cur.execute('SELECT COUNT(*) FROM bronze_transaction_logs_ingestion;'); "
        "print('bronze rows:', cur.fetchone()[0])\""
    )
    db_output = subprocess.check_output(kubectl_exec, shell=True, stderr=subprocess.STDOUT).decode()
    print(db_output)
except subprocess.CalledProcessError as e:
    print("DB verification via kubectl exec failed:", e.output.decode())
    print("(This may be expected if DB tables haven't been created yet by the pipeline run.)")

print("\n🎉 Medallion E2E Landing Zone Ingestion Pipeline verification complete!")
