"""
S3 utility module for uploading and downloading audio files.
"""

import os
import uuid
import boto3
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# S3 Configuration
# ---------------------------------------------------------------------------
S3_BUCKET = os.getenv("S3_BUCKET", "test-interview-audio")
S3_REGION = os.getenv("S3_REGION", "ap-south-1")

s3_client = boto3.client("s3", region_name=S3_REGION)


def upload_file_to_s3(local_path: str, prefix: str = "raw-audio/") -> str:
    """
    Upload a local file to S3 under the given prefix.
    Returns the S3 key of the uploaded object.
    """
    file_ext = os.path.splitext(local_path)[1].lstrip(".")
    unique_name = f"{uuid.uuid4()}.{file_ext}"
    s3_key = f"{prefix}{unique_name}"

    with open(local_path, "rb") as f:
        s3_client.upload_fileobj(
            Fileobj=f,
            Bucket=S3_BUCKET,
            Key=s3_key,
        )

    print(f"✅ Uploaded to s3://{S3_BUCKET}/{s3_key}")
    return s3_key


def download_file_from_s3(s3_key: str, local_path: str = None) -> str:
    """
    Download a file from S3 to a local path (defaults to /tmp/).
    Returns the local path of the downloaded file.
    """
    if local_path is None:
        filename = os.path.basename(s3_key)
        local_path = os.path.join("/tmp", filename)

    os.makedirs(os.path.dirname(local_path), exist_ok=True)

    s3_client.download_file(
        Bucket=S3_BUCKET,
        Key=s3_key,
        Filename=local_path,
    )

    print(f"✅ Downloaded s3://{S3_BUCKET}/{s3_key} -> {local_path}")
    return local_path


def get_s3_url(s3_key: str) -> str:
    """Return the public HTTPS URL for an S3 object."""
    return f"https://{S3_BUCKET}.s3.{S3_REGION}.amazonaws.com/{s3_key}"


if __name__ == "__main__":
    # Quick smoke test
    print(f"Bucket : {S3_BUCKET}")
    print(f"Region : {S3_REGION}")
    print("S3 utils module loaded successfully.")
