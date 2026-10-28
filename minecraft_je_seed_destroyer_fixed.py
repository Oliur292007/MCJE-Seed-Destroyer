import json
import os
import random
import time
import urllib.parse
import urllib.request
import urllib.error
from pathlib import Path

# MineSeedFinder documented Java endpoint.
API_URL = "https://www.mineseedfinder.com/GetStructures/java"
HISTORY_FILE = Path("posted_seeds.txt")

WEBHOOK_URL = os.environ["DISCORD_WEBHOOK_URL"]
ROLE_ID = os.environ["MINECRAFT_ROLE_ID"]

STRUCTURES = {
    5: "🏘️ Village",
    11: "🌀 Ruined Portal",
    14: "💎 Buried Treasure",
    24: "⚔️ Trial Chambers",
    13: "🏚️ Ancient City",
    7: "🚢 Shipwreck",
}

# API names expected for the structure IDs above.
EXPECTED_NAMES = {
    5: {"village"},
    11: {"ruined_portal"},
    14: {"buried_treasure", "treasure"},
    24: {"trial_chamber", "trial_chambers"},
    13: {"ancient_city"},
    7: {"shipwreck"},
}

MAX_CANDIDATES = 30
REQUEST_TIMEOUT = 45
API_RETRIES = 2


def read_history():
    if not HISTORY_FILE.exists():
        return set()
    return {
        line.strip()
        for line in HISTORY_FILE.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }


def normalize_name(value):
    return str(value or "").strip().lower().replace(" ", "_").replace("-", "_")


def scan_seed(seed):
    params = urllib.parse.urlencode({
        "seed": seed,
        "x": 0,
        "z": 0,
        "radius": 100,  # API radius is measured in chunks
        "max": 40,
        "types": ",".join(map(str, STRUCTURES)),
    })

    request = urllib.request.Request(
        f"{API_URL}?{params}",
        headers={"User-Agent": "Minecraft-JE-Seed-Destroyer/2.0"},
    )

    last_error = None
    for attempt in range(API_RETRIES + 1):
        try:
            with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
                data = json.loads(response.read().decode("utf-8"))

            if not isinstance(data, dict):
                raise RuntimeError("API response was not a JSON object.")
            if data.get("error"):
                raise RuntimeError(str(data["error"]))

            results = data.get("results")
            if not isinstance(results, list):
                raise RuntimeError("API response did not contain a valid results list.")

            return results

        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, RuntimeError) as exc:
            last_error = exc
            if attempt < API_RETRIES:
                time.sleep(2 * (attempt + 1))

    raise RuntimeError(f"MineSeedFinder request failed: {last_error}")


def validate_result(item):
    """Return (valid, normalized_name, x, z, reason)."""
    if not isinstance(item, dict):
        return False, "", None, None, "result is not an object"

    name = normalize_name(item.get("name"))
    if not name:
        return False, "", None, None, "missing structure name"

    try:
        # Reject bools, missing values, and non-integral coordinates.
        raw_x, raw_z = item.get("x"), item.get("z")
        if isinstance(raw_x, bool) or isinstance(raw_z, bool):
            raise ValueError
        x, z = int(raw_x), int(raw_z)
        if str(raw_x).strip() != str(x) or str(raw_z).strip() != str(z):
            # Allow JSON numeric values such as 48.0 only if integral.
            if float(raw_x) != x or float(raw_z) != z:
                raise ValueError
    except (TypeError, ValueError, OverflowError):
        return False, name, None, None, "missing or invalid X/Z coordinates"

    return True, name, x, z, ""


def get_structure_label(name):
    for structure_id, expected in EXPECTED_NAMES.items():
        if name in expected:
            return STRUCTURES[structure_id]
    return f"📌 {name.replace('_', ' ').title()}"


def choose_best_seed(history):
    best = None
    min_seed = -(2**63)
    max_seed = 2**63 - 1

    for _ in range(MAX_CANDIDATES):
        seed = random.randint(min_seed, max_seed)
        seed_string = str(seed)

        if seed_string in history:
            continue

        try:
            raw_results = scan_seed(seed)
        except Exception as exc:
            print(f"Scan failed for candidate {seed}: {exc}")
            time.sleep(2)
            continue

        valid_results = []
        for item in raw_results:
            valid, name, x, z, reason = validate_result(item)
            if not valid:
                print(f"Skipping invalid API result for seed {seed}: {reason}")
                continue

            # Only accept a structure name if it matches a known requested type.
            if not any(name in names for names in EXPECTED_NAMES.values()):
                print(f"Skipping unknown structure name {name!r} for seed {seed}")
                continue

            valid_results.append({
                "name": name,
                "x": x,
                "z": z,
            })

        if not valid_results:
            time.sleep(1)
            continue

        found_types = {item["name"] for item in valid_results}
        score = len(found_types)
        if "village" in found_types:
            score += 2
        if "ruined_portal" in found_types:
            score += 2
        if "buried_treasure" in found_types or "treasure" in found_types:
            score += 1
        if "ancient_city" in found_types:
            score += 1
        if "trial_chamber" in found_types or "trial_chambers" in found_types:
            score += 1

        candidate = (score, seed, valid_results)
        if best is None or score > best[0]:
            best = candidate

        if score >= 6:
            break

        time.sleep(1)

    return best


def post_to_discord(message):
    payload = json.dumps({
        "content": f"<@&{ROLE_ID}>\n{message}",
        "allowed_mentions": {
            "parse": [],
            "roles": [ROLE_ID],
        },
    }).encode("utf-8")

    request = urllib.request.Request(
        WEBHOOK_URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "Minecraft-JE-Seed-Destroyer/2.0",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            if response.status not in (200, 204):
                raise RuntimeError(f"Discord returned HTTP {response.status}")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        print(f"Discord HTTP {exc.code}: {detail[:300]}")
        raise RuntimeError(f"Discord posting failed: HTTP {exc.code}") from None


def format_message(seed, results):
    lines = [
        "💀 **MINECRAFT JE — SEED DESTROYER..!**",
        "",
        f"🎲 **Java Seed:** `{seed}`",
        "☕ **Edition:** Minecraft Java Edition",
        "📍 **Search area:** Within 100 chunks of X=0, Z=0",
        "",
        "**🔥 Nearby structure predictions (API results):**",
    ]

    for item in results[:20]:
        label = get_structure_label(item["name"])
        lines.append(
            f"• {label} — X: `{item['x']}`, Z: `{item['z']}`"
        )

    lines += [
        "",
        "🗺️ [Open Java Seed Map](https://mcseedmap.net/)",
        "🔎 [MineSeedFinder Java scanner](https://www.mineseedfinder.com/seedfinder)",
        "",
        "⚠️ Coordinates are API predictions, not independently verified in-game. "
        "For Trial Chambers, go to the listed X/Z and search underground; "
        "the marker is not a guaranteed entrance or loot location.",
        "",
        "━━━━━━━━━━━━━━━━━━━━",
        "💀 *Automatically selected by Minecraft JE Seed Destroyer*",
        "Powered by [MineSeedFinder](https://www.mineseedfinder.com/)",
    ]
    return "\n".join(lines)


def main():
    history = read_history()
    best = choose_best_seed(history)

    if best is None:
        raise RuntimeError(
            "No usable unposted Java seed found. Will retry at the next schedule."
        )

    _, seed, results = best
    message = format_message(seed, results)

    # Save history only after Discord confirms the post.
    post_to_discord(message)

    history.add(str(seed))
    HISTORY_FILE.write_text(
        "\n".join(sorted(history, key=lambda value: int(value))) + "\n",
        encoding="utf-8",
    )

    print(f"Posted new Java seed {seed} successfully.")


if __name__ == "__main__":
    main()
