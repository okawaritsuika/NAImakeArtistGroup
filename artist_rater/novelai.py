import json
import urllib.error
import urllib.request


SUBSCRIPTION_URL = "https://api.novelai.net/user/subscription"
REQUEST_TIMEOUT = 12
USER_AGENT = "DanbooruArtistRater/1.0 (local personal tool)"


class NovelAIError(Exception):
    def __init__(self, status_code, public_message):
        super().__init__(public_message)
        self.status = status_code
        self.status_code = status_code
        self.public_message = public_message


def test_novelai_subscription(app_key, opener=urllib.request.urlopen):
    request = urllib.request.Request(SUBSCRIPTION_URL, method="GET")
    request.add_header("Authorization", f"Bearer {app_key}")
    request.add_header("User-Agent", USER_AGENT)
    try:
        with opener(request, timeout=REQUEST_TIMEOUT) as response:
            data = json.loads(response.read().decode("utf-8"))
        steps = data.get("trainingStepsLeft") or {}
        anlas = int(steps.get("fixedTrainingStepsLeft", 0)) + int(
            steps.get("purchasedTrainingSteps", 0)
        )
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise NovelAIError(
                exc.code, "NovelAI App Key 인증에 실패했습니다."
            ) from None
        raise NovelAIError(
            502, f"NovelAI 요청에 실패했습니다. (HTTP {exc.code})"
        ) from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise NovelAIError(502, "NovelAI 서버에 연결할 수 없습니다.") from None
    except (UnicodeDecodeError, json.JSONDecodeError, AttributeError, TypeError, ValueError):
        raise NovelAIError(502, "NovelAI 응답을 해석할 수 없습니다.") from None
    return {"anlas": anlas}
