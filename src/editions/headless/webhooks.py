"""Ordered, at-least-once delivery of committed events, with persisted cursors."""
import asyncio
import hashlib
import hmac
import json
from urllib.parse import urlsplit
import httpx


class Webhook:
    def __init__(self, url, secret, cursor_path):
        parsed = urlsplit(url)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError('Webhook must use HTTPS without embedded credentials')
        if len(secret) < 32:
            raise ValueError('Webhook secret must contain at least 32 characters')
        self.url, self.secret, self.path = url, secret.encode(), cursor_path
        self.cursors = json.loads(cursor_path.read_text()) if cursor_path.exists() else {}

    async def deliver(self, client, camera_id, events):
        for event in events:
            body = json.dumps(event, separators=(',', ':')).encode()
            signature = hmac.new(self.secret, body, hashlib.sha256).hexdigest()
            response = await client.post(self.url, content=body, headers={
                'Content-Type': 'application/json', 'X-CCTV-Signature': 'sha256=' + signature,
                'X-CCTV-Event-ID': event['event_id']})
            response.raise_for_status()
            self.cursors[camera_id] = event['seq']
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix('.tmp')
            temporary.write_text(json.dumps(self.cursors), encoding='utf-8')
            temporary.replace(self.path)

    async def run(self, service):
        async with httpx.AsyncClient(timeout=5, follow_redirects=False, trust_env=False) as client:
            while True:
                service.license.check()
                for camera in service.all_status():
                    camera_id = camera['camera_id']
                    try:
                        events = await asyncio.to_thread(service.events, camera_id, self.cursors.get(camera_id, 0), 100)
                        await self.deliver(client, camera_id, events)
                    except (httpx.HTTPError, OSError, KeyError):
                        # Keep the last acknowledged cursor and retry on the next poll.
                        import logging
                        logging.getLogger(__name__).warning('Webhook delivery deferred for %s', camera_id)
                await asyncio.sleep(2)
