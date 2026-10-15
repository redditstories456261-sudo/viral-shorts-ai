"""S3-compatible object storage client built on boto3.

Key layout used by the pipeline:
    uploads/<upload_id>/source.mp4      raw user uploads (backend-owned)
    jobs/<job_id>/source.mp4            source video staged for the worker
    clips/<job_id>/<clip_id>.mp4        rendered vertical clips
"""

from __future__ import annotations

import logging
import os

import boto3
from botocore.exceptions import ClientError

log = logging.getLogger(__name__)


class StorageClient:
    """Thin wrapper around a boto3 S3 client with this project's key layout."""

    def __init__(
        self,
        endpoint_url: str = "",
        bucket: str = "",
        access_key: str = "",
        secret_key: str = "",
        region: str = "us-east-1",
    ) -> None:
        self.bucket = bucket
        self._s3 = boto3.client(
            "s3",
            endpoint_url=endpoint_url or None,
            aws_access_key_id=access_key or None,
            aws_secret_access_key=secret_key or None,
            region_name=region or "us-east-1",
        )

    @classmethod
    def from_settings(cls, settings) -> "StorageClient":
        return cls(
            endpoint_url=settings.s3_endpoint,
            bucket=settings.s3_bucket,
            access_key=settings.s3_access_key,
            secret_key=settings.s3_secret_key,
            region=settings.s3_region,
        )

    # -- key builders ------------------------------------------------------
    @staticmethod
    def upload_key(upload_id: str) -> str:
        return f"uploads/{upload_id}/source.mp4"

    @staticmethod
    def source_key(job_id: str) -> str:
        return f"jobs/{job_id}/source.mp4"

    @staticmethod
    def clip_key(job_id: str, clip_id: str) -> str:
        return f"clips/{job_id}/{clip_id}.mp4"

    # -- operations ---------------------------------------------------------
    def upload_file(self, local_path: str, key: str) -> str:
        size = os.path.getsize(local_path)
        log.info("uploading %s -> s3://%s/%s (%d bytes)", local_path, self.bucket, key, size)
        self._s3.upload_file(local_path, self.bucket, key)
        return key

    def download_file(self, key: str, local_path: str) -> str:
        directory = os.path.dirname(local_path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        log.info("downloading s3://%s/%s -> %s", self.bucket, key, local_path)
        self._s3.download_file(self.bucket, key, local_path)
        return local_path

    def presigned_url(self, key: str, expires: int = 3600) -> str:
        return self._s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=int(expires),
        )

    def delete_prefix(self, prefix: str) -> int:
        """Delete every object under ``prefix`` (paginated). Returns count deleted."""
        paginator = self._s3.get_paginator("list_objects_v2")
        deleted = 0
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            objects = page.get("Contents", [])
            if not objects:
                continue
            resp = self._s3.delete_objects(
                Bucket=self.bucket,
                Delete={"Objects": [{"Key": o["Key"]} for o in objects]},
            )
            deleted += len(resp.get("Deleted", []))
        log.info("deleted %d objects under prefix %s", deleted, prefix)
        return deleted

    def key_exists(self, key: str) -> bool:
        try:
            self._s3.head_object(Bucket=self.bucket, Key=key)
            return True
        except ClientError as exc:
            if exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode") == 404:
                return False
            raise
