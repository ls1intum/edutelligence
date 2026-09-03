"""Which URLs in a request the runner is willing to connect to.

The text is written by whoever opened the issue, and every URL in it is a
URL the runner would otherwise fetch while holding a GitHub token — from
inside the network the orchestrator and the database live on.
"""

from __future__ import annotations

from app import attachments

ATTACHMENT = "https://github.com/user-attachments/assets/69276878-e522-4e8a-bf5f-61fbadb04b43"


class TestWhatMayBeFetched:
    def test_a_github_attachment_is_taken(self):
        assert attachments.urls_in(f'<img src="{ATTACHMENT}" />') == [ATTACHMENT]

    def test_the_older_asset_style_is_taken(self):
        url = "https://github.com/ls1intum/edutelligence/assets/1354793/abc.png"
        assert attachments.urls_in(f"![shot]({url})") == [url]

    def test_a_stranger_s_host_is_not(self):
        # The finding: this would send the runner's token to attacker.example.
        assert attachments.urls_in("![x](https://attacker.example/x.png)") == []

    def test_the_runner_s_own_network_is_not(self):
        assert attachments.urls_in("![x](http://logos-orchestrator:8080/logosdb/scheduler_state)") == []

    def test_plain_http_is_not(self):
        assert attachments.urls_in(f"![x]({ATTACHMENT.replace('https', 'http')})") == []

    def test_a_lookalike_host_is_not(self):
        assert attachments.urls_in("![x](https://github.com.attacker.example/user-attachments/assets/1)") == []


class TestWhoMayHaveTheToken:
    def test_github_may(self):
        assert attachments.may_carry_the_token(ATTACHMENT)

    def test_the_storage_behind_it_may_not(self):
        # GitHub redirects an attachment to a signed S3 URL, and a signed URL
        # carries its own authorisation — ours has no business there.
        assert not attachments.may_carry_the_token(
            "https://github-production-user-asset-6210df.s3.amazonaws.com/1354793/645538273.png?X-Amz-Signature=x"
        )

    def test_nobody_else_may(self):
        assert not attachments.may_carry_the_token("https://attacker.example/x.png")


class TestWhereARedirectMayLead:
    def test_public_storage_is_followed(self):
        assert attachments.is_public("https://github-production-user-asset-6210df.s3.amazonaws.com/1/2.png")

    def test_a_private_address_is_not(self):
        assert not attachments.is_public("https://10.0.0.5/x.png")
        assert not attachments.is_public("https://127.0.0.1/x.png")

    def test_a_container_name_is_not(self):
        # A hop into the runner's own network is not a picture.
        assert not attachments.is_public("https://logos-orchestrator/x.png")
        assert not attachments.is_public("https://logos-db.local/x.png")


class TestOrderAndCount:
    """The files are numbered from this list, and the prompt lists them by
    that number — so "the first screenshot" has to mean the first one in the
    request, whichever notation it was written in."""

    def test_the_request_s_own_order_is_kept(self):
        body = f'<img src="{ATTACHMENT}1" />\n' f"and earlier in the reading order comes this one: ![a]({ATTACHMENT}2)"

        assert attachments.urls_in(body) == [f"{ATTACHMENT}1", f"{ATTACHMENT}2"]

    def test_a_markdown_image_before_a_tag_stays_first(self):
        body = f'![a]({ATTACHMENT}1) then <img src="{ATTACHMENT}2">'

        assert attachments.urls_in(body) == [f"{ATTACHMENT}1", f"{ATTACHMENT}2"]

    def test_the_same_url_twice_is_one_picture(self):
        assert attachments.urls_in(f"![a]({ATTACHMENT}) and again ![a]({ATTACHMENT})") == [ATTACHMENT]

    def test_a_request_full_of_pictures_gets_the_first_few(self):
        body = " ".join(f"![x]({ATTACHMENT}{index})" for index in range(20))

        taken = attachments.urls_in(body)

        assert len(taken) == attachments.MAX_IMAGES
        assert taken[0] == f"{ATTACHMENT}0"
