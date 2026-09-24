"""The reply an HTTP door gives a request that raised: the caller's error or
the server's fault, and never a traceback in the reply."""

from db import Refusal, web


def test_a_refusal_is_400_and_anything_else_500_without_a_traceback(capsys):
    assert web.failure(Refusal("x")) == ({"error": "x"}, 400)
    assert capsys.readouterr().err == ""
    # raised, not built: an error never raised carries no traceback to print
    try:
        raise KeyError("k")
    except KeyError as error:
        reply = web.failure(error)
    assert reply == ({"error": "KeyError: 'k'"}, 500)
    assert "Traceback" in capsys.readouterr().err
