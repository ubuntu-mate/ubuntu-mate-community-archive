#!/usr/bin/env python3
#
# Export JSON files from the Discourse database backup, taking care to only
# export public fields.
#
# In addition, Ubuntu MATE Community gave users an optional "opt-in"
# to preserve more of their profile (like avatars, bio, etc).
# By default, users' profile data will be stripped.
#
# This script can only be run by the administrator with the database backup.
#

import json
import random
import re
from pathlib import Path

import psycopg2
from psycopg2.extras import RealDictCursor

DB_NAME = "discourse"
DB_USER = "discourse"
DB_PASSWORD = "pass"
DB_HOST = "localhost"
DB_PORT = 5432

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "json"
MAX_JSON_BYTES = 50 * 1024 * 1024 - 1
SITE_URL = "https://ubuntu-mate.community"

# Categories to omit entirely from the archive (e.g. staff/multilingual).
EXCLUDED_CATEGORY_IDS = [43, 3, 4, 48, 46, 37, 33, 34, 35, 36]
PRESERVED_TOPIC_IDS = {4, 5, 6, 8}

# Discourse post_type values.
SMALL_ACTION_POST_TYPE = 3
WHISPER_POST_TYPE = 4

# Matches avatar thumbnails Discourse bakes into quoted post HTML, e.g.
# /user_avatar/ubuntu-mate.community/<username>/48/12345_2.png
AVATAR_URL_PATTERN = re.compile(r"/user_avatar/[^/\"']+/([^/\"']+)/\d+/[^\"'\s<>()]+")

# Discourse's system badge names can differ from their English display names.
SYSTEM_BADGE_NAMES = {
    "Basic User": "Basic",
    "Nice Post": "Nice Reply",
    "Good Post": "Good Reply",
    "Great Post": "Great Reply",
    "Solved 1": "Solved!",
    "Solved 2": "Guidance Counsellor",
    "Solved 3": "Know-it-All",
    "Solved 4": "Solution Institution",
}

# Discourse's built-in system badges don't store a description in the backup database.
SYSTEM_BADGE_DESCRIPTIONS = {
    "Editor": "First post edit",
    "Wiki Editor": "First wiki edit",
    "Basic User": "Granted all essential community functions",
    "Member": "Granted invitations, group messaging, more likes",
    "Regular": "Granted recategorize, rename, followed links, wiki, more likes",
    "Leader": "Granted global edit, pin, close, archive, split and merge, more likes",
    "Welcome": "Received a like",
    "Autobiographer": "Filled out profile information",
    "Anniversary": "Active member for a year, posted at least once",
    "Nice Post": "Received 10 likes on a reply",
    "Good Post": "Received 25 likes on a reply",
    "Great Post": "Received 50 likes on a reply",
    "Nice Topic": "Received 10 likes on a topic",
    "Good Topic": "Received 25 likes on a topic",
    "Great Topic": "Received 50 likes on a topic",
    "Nice Share": "Shared a post with 25 unique visitors",
    "Good Share": "Shared a post with 300 unique visitors",
    "Great Share": "Shared a post with 1000 unique visitors",
    "First Like": "Liked a post",
    "First Flag": "Flagged a post",
    "Promoter": "Invited a user",
    "Campaigner": "Invited 3 basic users",
    "Champion": "Invited 5 members",
    "First Share": "Shared a post",
    "First Link": "Added a link to another topic",
    "First Quote": "Quoted a post",
    "Read Guidelines": "Read the community guidelines",
    "Reader": "Read every reply in a topic with more than 100 replies",
    "Popular Link": "Posted an external link with 50 clicks",
    "Hot Link": "Posted an external link with 300 clicks",
    "Famous Link": "Posted an external link with 1000 clicks",
    "Appreciated": "Received 1 like on 20 posts",
    "Respected": "Received 2 likes on 100 posts",
    "Admired": "Received 5 likes on 300 posts",
    "Out of Love": "Used the maximum number of likes in a day",
    "Higher Love": "Used the maximum number of likes in a day 5 times",
    "Crazy in Love": "Used the maximum number of likes in a day 20 times",
    "Thank You": "Has 20 liked posts and gave 10 likes",
    "Gives Back": "Has 100 liked posts and gave 100 likes",
    "Empathetic": "Has 500 liked posts and gave 1000 likes",
    "First Emoji": "Used an Emoji in a Post",
    "First Mention": "Mentioned a user in a post",
    "First Onebox": "Posted a link that was oneboxed",
    "First Reply By Email": "Replied to a post via email",
    "New User of the Month": "Outstanding contributions in their first month",
    "Enthusiast": "Visited 10 consecutive days",
    "Aficionado": "Visited 100 consecutive days",
    "Devotee": "Visited 365 consecutive days",
    # From the discourse-solved plugin.
    "Solved 1": "Have a reply marked as a Solution",
    "Solved 2": "Have 10 replies marked as Solutions",
    "Solved 3": "Have 50 replies marked as Solutions",
    "Solved 4": "Have 150 replies marked as Solutions",
    # From the discourse-reactions plugin.
    "First Reaction": "Reacted to the post",
}


class DiscourseExporter:
    """Reads the Discourse database and writes it out as static JSON files."""
    def __init__(self):
        self.conn = psycopg2.connect(
            dbname=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD,
            host=DB_HOST,
            port=DB_PORT,
            cursor_factory=RealDictCursor,
        )
        self.scrubbed_usernames = set()  # username_lower -> did not opt in to full profile preservation
        self.included_topic_ids = set()  # topic IDs actually written to topics.json
        self.tags = []

    def export_all(self):
        """Export all tables to json/*.json."""
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

        self._load_scrubbed_usernames()
        self._export_categories()
        self._export_users()
        self._export_badges()
        self._export_user_badges()
        self._export_tags()
        self._export_topics()
        self._export_posts()
        self._export_groups()

        print("Done!")

    def _write_json(self, filename, data):
        path = OUTPUT_DIR / filename
        parts = []
        records = []
        size = 4

        def write_part():
            part = OUTPUT_DIR / f"{path.stem}.{len(parts) + 1}.json"
            part.write_bytes(b"[\n" + b",\n".join(records) + b"\n]")
            parts.append(part)

        for record in data:
            text = json.dumps(record, indent=2, ensure_ascii=False)
            encoded = ("  " + text.replace("\n", "\n  ")).encode("utf-8")
            if len(encoded) + 4 > MAX_JSON_BYTES:
                raise ValueError(f"A record in {filename} exceeds the JSON size limit")
            if records and size + 2 + len(encoded) > MAX_JSON_BYTES:
                write_part()
                records = []
                size = 4
            size += len(encoded) + (2 if records else 0)
            records.append(encoded)
        write_part()

        if len(parts) == 1:
            parts[0].replace(path)
            parts = [path]
        for old in [path, *OUTPUT_DIR.glob(f"{path.stem}.*.json")]:
            if old not in parts and (old == path or old.stem.removeprefix(path.stem + ".").isdigit()):
                old.unlink(missing_ok=True)
        print(f"  Wrote {len(parts)} file(s) for {filename} ({len(data):,} records)")

    def _load_scrubbed_usernames(self):
        """Load usernames of users who did not opt in to full profile preservation."""
        print("Loading privacy preferences...")
        cur = self.conn.cursor()
        cur.execute("""
            SELECT u.username_lower, ucf.value as preservation_preference
            FROM users u
            LEFT JOIN user_custom_fields ucf ON u.id = ucf.user_id AND ucf.name = 'user_field_3'
            WHERE u.id > 0
        """)

        for row in cur.fetchall():
            preference = (row["preservation_preference"] or "").lower()
            if "full profile" not in preference:
                self.scrubbed_usernames.add(row["username_lower"])

        cur.close()
        print(f"  {len(self.scrubbed_usernames)} users did not opt in to full profile preservation")

    def _scrub_avatar_references(self, text):
        """Blank out avatar thumbnails embedded for users who opted out of preservation."""
        if not text:
            return text

        def _replace(match):
            if match.group(1).lower() in self.scrubbed_usernames:
                return ""
            return match.group(0)

        return AVATAR_URL_PATTERN.sub(_replace, text)

    @staticmethod
    def _make_links_relative(text):
        """Remove the archived site's domain from serialized links."""
        if not text:
            return text
        return text.replace(SITE_URL, "")

    def _export_categories(self):
        """Export categories.json."""
        print("Exporting categories...")
        cur = self.conn.cursor()
        cur.execute("""
            SELECT id, name, color, text_color, slug, description,
                   topic_count, post_count, position, parent_category_id,
                   uploaded_logo_id, uploaded_background_id
            FROM categories
            ORDER BY position
        """)

        categories = []
        for row in cur.fetchall():
            category = dict(row)
            if category["id"] in EXCLUDED_CATEGORY_IDS:
                continue

            if category["id"] == 1:
                category["description"] = "Other topics related to Ubuntu, computing and the Linux ecosystem."

            categories.append(category)

        cur.close()
        self._write_json("categories.json", categories)

    def _export_users(self):
        """Export users.json, scrubbing profiles that opted out of preservation."""
        print("Exporting users...")
        cur = self.conn.cursor()
        cur.execute("""
            SELECT u.id, u.username, u.username_lower, u.name, u.title,
                   u.created_at, u.last_seen_at, u.last_posted_at,
                   u.trust_level, u.admin, u.moderator, u.active,
                   u.uploaded_avatar_id, u.primary_group_id,
                   us.topic_count, us.post_count, us.likes_given, us.likes_received,
                   us.topics_entered, us.posts_read_count,
                   us.days_visited, us.time_read,
                   up.bio_raw, up.bio_cooked, up.location, up.website,
                   up.profile_background_upload_id, up.card_background_upload_id,
                   avatar_upload.url as avatar_url,
                   profile_bg_upload.url as profile_background_url,
                   card_bg_upload.url as card_background_url,
                   ucf.value as preservation_preference
            FROM users u
            LEFT JOIN user_stats us ON u.id = us.user_id
            LEFT JOIN user_profiles up ON u.id = up.user_id
            LEFT JOIN uploads avatar_upload ON u.uploaded_avatar_id = avatar_upload.id
            LEFT JOIN uploads profile_bg_upload ON up.profile_background_upload_id = profile_bg_upload.id
            LEFT JOIN uploads card_bg_upload ON up.card_background_upload_id = card_bg_upload.id
            LEFT JOIN user_custom_fields ucf ON u.id = ucf.user_id AND ucf.name = 'user_field_3'
            WHERE u.id > 0 OR u.id = -1
            ORDER BY u.id
        """)

        users = []
        for row in cur.fetchall():
            user = dict(row)
            for field in ["created_at", "last_seen_at", "last_posted_at"]:
                if user.get(field):
                    user[field] = user[field].isoformat()

            user["bio_cooked"] = self._make_links_relative(
                self._scrub_avatar_references(user.get("bio_cooked"))
            )
            self._scrub_profile(user)
            users.append(user)

        cur.close()
        self._write_json("users.json", users)

    @staticmethod
    def _scrub_profile(user):
        """Strip profile data unless the user opted in to preserve their full profile."""
        if user["id"] == -1:
            return

        preference = (user.get("preservation_preference") or "").lower()

        if "full profile" in preference:
            return

        fields_to_scrub = [
            "name", "title", "uploaded_avatar_id", "avatar_url",
            "bio_raw", "bio_cooked", "location", "website",
            "profile_background_upload_id", "card_background_upload_id",
            "profile_background_url", "card_background_url",
        ]

        if "anonymous" in preference:
            anon_num = random.randint(1000000, 9999999)
            user["username"] = f"anon{anon_num}"
            user["username_lower"] = user["username"]

        for field in fields_to_scrub:
            user[field] = None

    def _export_badges(self):
        """Export badges.json."""
        print("Exporting badges...")
        cur = self.conn.cursor()
        cur.execute("""
            SELECT b.id, b.name, b.description, b.long_description,
                   b.badge_type_id, b.grant_count, b.icon, b.image_upload_id,
                   b.allow_title, b.multiple_grant, b.listable, b.enabled,
                   b.badge_grouping_id, b.system,
                   bt.name as badge_type_name,
                   bg.name as badge_grouping_name, bg.position as grouping_position
            FROM badges b
            LEFT JOIN badge_types bt ON b.badge_type_id = bt.id
            LEFT JOIN badge_groupings bg ON b.badge_grouping_id = bg.id
            WHERE b.enabled = true
            ORDER BY bg.position, b.badge_type_id, b.name
        """)

        badges = []
        for row in cur.fetchall():
            badge = dict(row)
            source_name = badge["name"]
            if not badge["description"] and badge["system"]:
                badge["description"] = SYSTEM_BADGE_DESCRIPTIONS.get(source_name)
            badge["name"] = SYSTEM_BADGE_NAMES.get(source_name, source_name)
            badge["slug"] = re.sub(r"[^a-z0-9]+", "-", badge["name"].lower()).strip("-")
            badges.append(badge)

        cur.close()
        self._write_json("badges.json", badges)

    def _export_user_badges(self):
        """Export user_badges.json (badge grants)."""
        print("Exporting user badges...")
        cur = self.conn.cursor()
        cur.execute("""
            SELECT id, badge_id, user_id, granted_at, granted_by_id, post_id, seq
            FROM user_badges
            ORDER BY granted_at DESC
        """)

        user_badges = []
        for row in cur.fetchall():
            user_badge = dict(row)
            if user_badge["granted_at"]:
                user_badge["granted_at"] = user_badge["granted_at"].isoformat()
            user_badges.append(user_badge)

        cur.close()
        self._write_json("user_badges.json", user_badges)

    def _export_tags(self):
        """Export tags.json which were optional for organising topics."""
        print("Exporting tags...")
        cur = self.conn.cursor()
        cur.execute("""
            SELECT id, name, slug, public_topic_count, pm_topic_count,
                   description, created_at, updated_at
            FROM tags
            ORDER BY public_topic_count DESC
        """)

        tags = []
        tags_by_id = {}
        for row in cur.fetchall():
            tag = dict(row)
            if tag["created_at"]:
                tag["created_at"] = tag["created_at"].isoformat()
            if tag["updated_at"]:
                tag["updated_at"] = tag["updated_at"].isoformat()
            tag["group_names"] = []
            tags.append(tag)
            tags_by_id[tag["id"]] = tag

        cur.execute("""
            SELECT m.tag_id, g.name
            FROM tag_group_memberships m
            JOIN tag_groups g ON g.id = m.tag_group_id
            ORDER BY g.name
        """)
        for row in cur.fetchall():
            tag = tags_by_id.get(row["tag_id"])
            if tag:
                tag["group_names"].append(row["name"])

        cur.close()
        self.tags = tags

    def _export_topics(self):
        """Export topics.json, including tags, participants and the solved post."""
        print("Exporting topics...")
        cur = self.conn.cursor()
        cur.execute("""
            SELECT t.id, t.title, t.slug, t.posts_count, t.reply_count,
                   t.views, t.like_count, t.word_count, t.created_at, t.updated_at,
                   t.last_posted_at, t.user_id, t.last_post_user_id,
                   t.category_id, t.visible, t.closed, t.archived,
                   t.pinned_at, t.pinned_globally, t.highest_post_number,
                   t.featured_link, t.archetype
            FROM topics t
            WHERE t.deleted_at IS NULL AND t.visible = true
            ORDER BY t.id
        """)

        topics = []
        topics_by_id = {}
        for row in cur.fetchall():
            topic = dict(row)

            if topic.get("unlisted") or topic.get("archetype") == "private_message":
                continue
            if topic.get("category_id") in EXCLUDED_CATEGORY_IDS and topic["id"] not in PRESERVED_TOPIC_IDS:
                continue

            for field in ["created_at", "updated_at", "last_posted_at", "pinned_at"]:
                if topic.get(field):
                    topic[field] = topic[field].isoformat()

            topic["tag_ids"] = []
            topic["participants"] = []
            topic["solved_post_id"] = None

            topics.append(topic)
            topics_by_id[topic["id"]] = topic

        cur.execute("SELECT topic_id, tag_id FROM topic_tags ORDER BY topic_id")
        for row in cur.fetchall():
            topic = topics_by_id.get(row["topic_id"])
            if topic:
                topic["tag_ids"].append(row["tag_id"])

        cur.execute("""
            SELECT p.topic_id, p.user_id, COUNT(*) as post_count
            FROM posts p
            WHERE p.deleted_at IS NULL
            GROUP BY p.topic_id, p.user_id
            ORDER BY p.topic_id, post_count DESC
        """)
        for row in cur.fetchall():
            topic = topics_by_id.get(row["topic_id"])
            if topic:
                topic["participants"].append({"user_id": row["user_id"], "post_count": row["post_count"]})

        cur.execute("""
            SELECT p.topic_id, p.id AS post_id
            FROM post_custom_fields pcf
            JOIN posts p ON p.id = pcf.post_id
            WHERE p.deleted_at IS NULL
              AND pcf.name = 'is_accepted_answer'
              AND COALESCE(LOWER(pcf.value), '') IN ('1', 't', 'true', 'yes')
            ORDER BY p.topic_id, p.post_number
        """)
        for row in cur.fetchall():
            topic = topics_by_id.get(row["topic_id"])
            # Keep first solved post when duplicates exist.
            if topic and topic["solved_post_id"] is None:
                topic["solved_post_id"] = row["post_id"]

        cur.close()
        self.included_topic_ids = set(topics_by_id.keys())
        self._write_json("topics.json", topics)

        # Tags with no exported topics get no JSON and therefore no HTML page
        used_tag_ids = {tid for t in topics for tid in t["tag_ids"]}
        self._write_json("tags.json", [t for t in self.tags if t["id"] in used_tag_ids])

    def _export_posts(self):
        """Export posts.json, including the users who liked each post."""
        print("Exporting posts...")
        cur = self.conn.cursor()
        cur.execute("""
            SELECT p.id, p.user_id, p.topic_id, p.post_number,
                   p.raw, p.cooked, p.created_at, p.updated_at,
                   p.reply_to_post_number, p.reply_count, p.quote_count,
                   p.like_count, p.reads, p.score, p.hidden, p.version,
                   p.post_type, p.action_code
            FROM posts p
            WHERE p.deleted_at IS NULL
              AND p.post_type != %s
            ORDER BY p.topic_id, p.post_number
        """, (WHISPER_POST_TYPE,))

        posts = []
        posts_by_id = {}
        for row in cur.fetchall():
            post = dict(row)

            # Only keep posts belonging to topics we actually exported (skips
            # private messages, unlisted/deleted topics, excluded categories).
            if post["topic_id"] not in self.included_topic_ids:
                continue

            for field in ["created_at", "updated_at"]:
                if post.get(field):
                    post[field] = post[field].isoformat()

            post["cooked"] = self._make_links_relative(
                self._scrub_avatar_references(post.get("cooked"))
            )
            post["raw"] = self._make_links_relative(
                self._scrub_avatar_references(post.get("raw"))
            )

            # Removing avatars may result in empty src tags for quotes
            if post.get("cooked"):
                post["cooked"] = re.sub(r'<img alt="" width="24" height="24" src="" class="avatar">', '', post["cooked"])

            is_action = post["post_type"] == SMALL_ACTION_POST_TYPE and bool(post.get("action_code"))
            has_content = bool((post.get("raw") or "").strip()) or bool((post.get("cooked") or "").strip())
            if not has_content and not is_action:
                continue

            post["like_user_ids"] = []
            posts.append(post)
            posts_by_id[post["id"]] = post

        cur.execute("""
            SELECT pa.post_id, pa.user_id
            FROM post_actions pa
            JOIN post_action_types pat ON pa.post_action_type_id = pat.id
            WHERE pa.deleted_at IS NULL
              AND pat.name_key = 'like'
            ORDER BY pa.post_id, pa.id
        """)
        for row in cur.fetchall():
            post = posts_by_id.get(row["post_id"])
            if post:
                post["like_user_ids"].append(row["user_id"])

        self._attach_polls(cur, posts_by_id)

        cur.close()
        self._write_json("posts.json", posts)

    @staticmethod
    def _attach_polls(cur, posts_by_id):
        """Attach aggregate poll results (no per-user votes) to posts as post["polls"]."""
        for post in posts_by_id.values():
            post["polls"] = []

        cur.execute("""
            SELECT id, post_id, name, type, status, close_at
            FROM polls
            ORDER BY post_id, id
        """)
        polls_by_id = {}
        for row in cur.fetchall():
            post = posts_by_id.get(row["post_id"])
            if not post:
                continue
            poll = {
                "name": row["name"],
                "type": row["type"],
                "status": row["status"],
                "close_at": row["close_at"].isoformat() if row["close_at"] else None,
                "voters": 0,
                "options": {},
            }
            post["polls"].append(poll)
            polls_by_id[row["id"]] = poll

        options_by_id = {}
        cur.execute("""
            SELECT id, poll_id, digest, anonymous_votes
            FROM poll_options
            ORDER BY poll_id, id
        """)
        for row in cur.fetchall():
            poll = polls_by_id.get(row["poll_id"])
            if poll:
                poll["options"][row["digest"]] = row["anonymous_votes"] or 0
                options_by_id[row["id"]] = (poll, row["digest"])

        cur.execute("SELECT poll_id, poll_option_id, user_id FROM poll_votes")
        voters = {}
        for row in cur.fetchall():
            entry = options_by_id.get(row["poll_option_id"])
            if not entry:
                continue
            poll, digest = entry
            poll["options"][digest] += 1
            voters.setdefault(row["poll_id"], set()).add(row["user_id"])

        for poll_id, poll in polls_by_id.items():
            poll["voters"] = len(voters.get(poll_id, ()))

    def _export_groups(self):
        """Export groups.json, including member user IDs."""
        print("Exporting groups...")
        cur = self.conn.cursor()
        cur.execute("""
            SELECT g.id, g.name, g.user_count, g.full_name,
                   g.bio_raw, g.bio_cooked, g.public_admission,
                   g.public_exit, g.allow_membership_requests,
                   g.visibility_level, g.primary_group,
                   g.title, g.flair_icon, g.flair_upload_id,
                   g.flair_bg_color, g.flair_color
            FROM groups g
            WHERE g.automatic = false OR g.id IN (0, 1, 2, 3, 10, 11, 12, 13, 14, 15)
            ORDER BY g.id
        """)

        groups = []
        groups_by_id = {}
        for row in cur.fetchall():
            group = dict(row)
            group["bio_cooked"] = self._make_links_relative(
                self._scrub_avatar_references(group.get("bio_cooked"))
            )
            group["member_user_ids"] = []
            groups.append(group)
            groups_by_id[group["id"]] = group

        cur.execute("SELECT group_id, user_id FROM group_users ORDER BY group_id, user_id")
        for row in cur.fetchall():
            group = groups_by_id.get(row["group_id"])
            if group:
                group["member_user_ids"].append(row["user_id"])

        cur.close()
        self._write_json("groups.json", groups)

    def close(self):
        if self.conn:
            self.conn.close()


def main():
    exporter = DiscourseExporter()
    try:
        exporter.export_all()
    finally:
        exporter.close()


if __name__ == "__main__":
    main()
