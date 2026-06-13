import json
import urllib.error
import urllib.request


SUBSCRIPTION_URL = "https://api.novelai.net/user/subscription"
REQUEST_TIMEOUT = 12
USER_AGENT = "DanbooruArtistRater/1.0 (local personal tool)"
MAX_SUBSCRIPTION_BYTES = 1024 * 1024


class NovelAIError(Exception):
    def __init__(self, status_code, public_message):
        super().__init__(public_message)
        self.status = status_code
        self.status_code = status_code
        self.public_message = public_message


class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _default_open(request, timeout):
    return urllib.request.build_opener(NoRedirectHandler()).open(
        request, timeout=timeout
    )


def _subscription_total(data):
    if not isinstance(data, dict):
        raise ValueError("Response must be an object.")
    steps = data.get("trainingStepsLeft")
    if not isinstance(steps, dict):
        raise ValueError("trainingStepsLeft must be an object.")
    values = []
    for key in ("fixedTrainingStepsLeft", "purchasedTrainingSteps"):
        value = steps.get(key)
        if type(value) is not int or value < 0:
            raise ValueError(f"{key} must be a nonnegative integer.")
        values.append(value)
    return sum(values)


def test_novelai_subscription(app_key, opener=None):
    request = urllib.request.Request(SUBSCRIPTION_URL, method="GET")
    request.add_unredirected_header("Authorization", f"Bearer {app_key}")
    request.add_header("User-Agent", USER_AGENT)
    open_request = opener or _default_open
    try:
        with open_request(request, timeout=REQUEST_TIMEOUT) as response:
            raw = response.read(MAX_SUBSCRIPTION_BYTES + 1)
        if len(raw) > MAX_SUBSCRIPTION_BYTES:
            raise ValueError("Subscription response is too large.")
        data = json.loads(raw.decode("utf-8"))
        anlas = _subscription_total(data)
    except urllib.error.HTTPError as exc:
        try:
            if exc.code in (401, 403):
                raise NovelAIError(
                    exc.code, "NovelAI App Key authentication failed."
                ) from None
            raise NovelAIError(
                502, f"NovelAI request failed. (HTTP {exc.code})"
            ) from None
        finally:
            exc.close()
    except (urllib.error.URLError, TimeoutError, OSError):
        raise NovelAIError(502, "Could not connect to the NovelAI server.") from None
    except (UnicodeDecodeError, json.JSONDecodeError, AttributeError, TypeError, ValueError):
        raise NovelAIError(502, "Could not parse the NovelAI response.") from None
    return {"anlas": anlas}
