"""Small synchronous SDK. Only the Python standard library is required."""
import json
from urllib.request import Request, urlopen
from urllib.parse import quote


class HeadlessClient:
    def __init__(self, token, base_url='http://127.0.0.1:8766'):
        self.base_url, self.token = base_url.rstrip('/'), token

    def request(self, method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        request = Request(self.base_url + '/api/v1' + path, data=data, method=method,
                          headers={'Authorization': 'Bearer ' + self.token, 'Content-Type': 'application/json'})
        with urlopen(request, timeout=15) as response:
            return json.loads(response.read()) if response.status != 204 else None

    def status(self):
        return self.request('GET', '/status')

    def add_camera(self, camera_id, url):
        return self.request('POST', '/cameras', {'camera_id': camera_id, 'url': url})

    def calibrate(self, camera_id, profile):
        return self.request('PUT', '/cameras/' + quote(camera_id, safe='') + '/analytics', profile)

    def start(self, camera_id, preview_only=False):
        return self.request('POST', '/cameras/' + quote(camera_id, safe='') + '/start?preview_only=' + str(preview_only).lower())

    def stop(self, camera_id):
        return self.request('POST', '/cameras/' + quote(camera_id, safe='') + '/stop')

    def events(self, camera_id, after=0):
        return self.request('GET', '/cameras/' + quote(camera_id, safe='') + '/events?after=' + str(int(after)))


if __name__ == '__main__':
    import os
    print(json.dumps(HeadlessClient(os.environ['CCTV_HEADLESS_TOKEN']).status(), indent=2))
