#!/usr/bin/liquidsoap

# Radio Automation Server - Liquidsoap 2.1 Configuration
# With Moderation Panel Support (Music Bed, Ducking, Instant Jingles)

# Allow running as root in container
settings.init.allow_root.set(true)

# Log settings
log.file.set(true)
log.file.path.set("/var/log/liquidsoap/liquidsoap.log")
log.level.set(3)

# Telnet server for remote control
settings.server.telnet.set(true)
settings.server.telnet.bind_addr.set("127.0.0.1")
settings.server.telnet.port.set(1234)

# FFmpeg decoder is enabled by default in Liquidsoap 2.1
# Supports all common audio formats: mp3, flac, ogg, wav, aac, m4a, wma, opus

# ========== CROSSFADE SETTINGS ==========

# Default crossfade values (in seconds)
# These are read from /data/stream_settings.json if available
crossfade_music_fade_in = ref(0.5)
crossfade_music_fade_out = ref(0.5)
crossfade_jingle_fade_in = ref(0.0)
crossfade_jingle_fade_out = ref(0.0)
crossfade_moderation_fade_in = ref(0.0)
crossfade_moderation_fade_out = ref(0.0)

# Load settings from JSON file at startup
def load_crossfade_settings() =
    settings_file = "/data/stream_settings.json"
    if file.exists(settings_file) then
        log("Loading crossfade settings from #{settings_file}")
        content = file.contents(settings_file)

        # Simple string-based extraction
        def get_float_value(key, def_val) =
            # Find pattern: "key": value
            search_pattern = "\"#{key}\": "
            if string.contains(substring=search_pattern, content) then
                # Split at the pattern
                parts = string.split(separator=search_pattern, content)
                if list.length(parts) > 1 then
                    # Get the part after the pattern
                    value_part = list.nth(default="", parts, 1)
                    # Split at comma to get just the value
                    value_parts = string.split(separator=",", value_part)
                    if list.length(value_parts) > 0 then
                        raw_value = list.nth(default="0", value_parts, 0)
                        # Clean up (remove spaces and braces)
                        clean_value = string.replace(pattern=" ", fun(_) -> "", raw_value)
                        clean_value = string.replace(pattern="}", fun(_) -> "", clean_value)
                        # Parse to float
                        float_of_string(default=def_val, clean_value)
                    else
                        def_val
                    end
                else
                    def_val
                end
            else
                def_val
            end
        end

        crossfade_music_fade_in := get_float_value("crossfade_music_fade_in", 0.5)
        crossfade_music_fade_out := get_float_value("crossfade_music_fade_out", 0.5)
        crossfade_jingle_fade_in := get_float_value("crossfade_jingle_fade_in", 0.0)
        crossfade_jingle_fade_out := get_float_value("crossfade_jingle_fade_out", 0.0)
        crossfade_moderation_fade_in := get_float_value("crossfade_moderation_fade_in", 0.0)
        crossfade_moderation_fade_out := get_float_value("crossfade_moderation_fade_out", 0.0)

        log("Loaded: music_in=#{!crossfade_music_fade_in}, music_out=#{!crossfade_music_fade_out}, jingle_in=#{!crossfade_jingle_fade_in}, jingle_out=#{!crossfade_jingle_fade_out}")
    else
        log("No settings file found at #{settings_file}, using defaults")
    end
end

# Load settings on startup
load_crossfade_settings()

# ========== MODERATION PANEL - DYNAMIC VOLUME CONTROLS ==========

# Volume reference variables (controlled via telnet)
bed_volume = ref(0.3)
bed_ducking_level = ref(0.15)
ducking_active = ref(false)
bed_enabled = ref(false)
jingle_volume = ref(1.0)
mic_enabled = ref(false)
mic_volume = ref(1.0)
mic_auto_duck = ref(true)

# ========== MAIN RADIO SOURCES ==========

# Request queue for dynamic track insertion
queue = request.queue(id="queue")

# Moderation queue - plays recorded moderations after current track
moderation_queue = request.queue(id="moderation_queue")

# Main music playlist - starts playing immediately on boot
# mode="randomize" shuffles the playlist once, then plays in order
# This prevents the same track from repeating too soon
# IMPORTANT: Uses playlist file that contains only ACTIVE tracks
# Playlist is sorted by play history to avoid repetition (recent songs at end)
# reload=3600 means playlist is reloaded every hour (prevents too frequent re-shuffling)
music = playlist(
    id="music",
    mode="randomize",
    reload=3600,
    "/data/playlists/music.m3u"
)

# Make playlist safe (silence if empty/loading)
music_safe = mksafe(music)

# Silent fallback (emergency) - always available
silence = blank(id="silence")

# Main source chain with priorities:
# 1. moderation_queue (highest priority - plays after current track ends)
# 2. queue (manual track insertions)
# 3. music_safe (playlist)
# 4. silence (emergency fallback)
#
# track_sensitive=true ensures we wait for tracks to finish before switching
radio_base = fallback(
    track_sensitive=true,
    [moderation_queue, queue, music_safe, silence]
)

# Apply crossfade for smooth transitions between all sources
# Uses the configured music fade settings
# IMPORTANT: duration must be set to match fade times, otherwise default 5s is used
radio_base = crossfade(
    duration=max(0.1, !crossfade_music_fade_in + !crossfade_music_fade_out),
    fade_out=!crossfade_music_fade_out,
    fade_in=!crossfade_music_fade_in,
    radio_base
)

# Make the final source infallible
radio_base = mksafe(radio_base)

# Normalize audio levels
radio_base = normalize(target=-16., radio_base)

# ========== MUSIC BED SOURCE ==========

# Music bed playlist (loops background music for moderation)
# IMPORTANT: Uses playlist file that contains only ACTIVE tracks
# reload=3600 means playlist is reloaded every hour
musicbed_playlist = playlist(
    id="musicbed",
    mode="random",
    reload=3600,
    "/data/playlists/musicbeds.m3u"
)

# Make music bed safe (returns silence if no files)
musicbed_safe = mksafe(musicbed_playlist)

# Apply dynamic volume based on ducking state
# When ducking_active is TRUE, use lower ducking level
# When ducking_active is FALSE, use normal bed volume
def get_bed_volume() =
    if !ducking_active then
        !bed_ducking_level  # Ducking is ON -> lower volume
    else
        !bed_volume         # Ducking is OFF -> normal volume
    end
end

# Music bed with volume control
musicbed_amplified = amplify(get_bed_volume, musicbed_safe)

# Switch to enable/disable music bed
musicbed_switched = switch(
    track_sensitive=false,
    [
        ({!bed_enabled}, musicbed_amplified),
        ({true}, blank())
    ]
)

# ========== INSTANT JINGLE SOURCE ==========

# Instant jingle queue - plays immediately over everything
instant_jingle_queue = request.queue(id="instant_jingles")

# Apply jingle volume
instant_jingles = amplify({!jingle_volume}, instant_jingle_queue)

# ========== MICROPHONE INPUT (Browser WebSocket via HTTP) ==========

# HTTP input for browser microphone - Flask streams audio here
# Using input.harbor.http for low-latency raw audio streaming
mic_input = input.harbor(
    id="mic_harbor",
    port=9998,
    "/mic",
    user="source",
    password="hackme",
    buffer=0.5,          # Small buffer for low latency (500ms)
    max=2.0              # Max buffer before dropping
)

# Make mic input safe (silence when not connected)
mic_safe = mksafe(mic_input)

# Apply mic volume
mic_amplified = amplify({!mic_volume}, mic_safe)

# Switch to enable/disable mic
mic_switched = switch(
    track_sensitive=false,
    [
        ({!mic_enabled}, mic_amplified),
        ({true}, blank())
    ]
)

# ========== AUDIO MIXING CHAIN ==========

# Function to get main music volume (ducked when active)
def get_music_volume() =
    if !ducking_active then
        !bed_ducking_level  # Ducking is ON -> lower volume
    else
        1.0                 # Ducking is OFF -> full volume
    end
end

# Apply ducking to main radio source
radio_ducked = amplify(get_music_volume, radio_base)

# Layer 1: Main radio (ducked) + Music bed (added together)
radio_with_bed = add(
    normalize=false,
    [radio_ducked, musicbed_switched]
)

# Layer 2: Add microphone input
radio_with_mic = add(
    normalize=false,
    [radio_with_bed, mic_switched]
)

# Layer 3: Instant jingles play OVER everything (mixed, not replacing)
# Using add() so jingles play simultaneously with music
radio_with_jingles = add(
    normalize=false,
    [radio_with_mic, instant_jingles]
)

# Final normalization
radio = normalize(target=-16., radio_with_jingles)

# ========== METADATA HANDLING ==========

def apply_metadata(m) =
    title = m["title"]
    artist = m["artist"]
    filename = m["filename"]

    # Log current track
    log("Now playing: #{artist} - #{title} (#{filename})")

    m
end

radio = map_metadata(apply_metadata, radio)

# ========== OUTPUT TO ICECAST ==========

output.icecast(
    %mp3(bitrate=192, samplerate=44100, stereo=true),
    host="localhost",
    port=8000,
    password="hackme",
    mount="/stream",
    name="Radio Automation",
    description="Automated Radio Stream",
    genre="Various",
    url="http://localhost:8080",
    public=false,
    fallible=true,
    radio
)

# ========== TELNET COMMANDS - QUEUE CONTROL ==========

server.register(
    "push",
    fun(uri) -> begin
        queue.push(request.create(uri))
        "Track queued: #{uri}"
    end
)

server.register(
    "skip",
    fun(_) -> begin
        # Skip the current track - ends current track and triggers fallback
        # Fallback will check moderation_queue first, then queue, then music
        source.skip(radio_base)
        "Track skipped"
    end
)

# ========== TELNET COMMANDS - MUSIC BED CONTROL ==========

server.register(
    "bed.on",
    fun(_) -> begin
        bed_enabled := true
        "Music bed enabled"
    end
)

server.register(
    "bed.off",
    fun(_) -> begin
        bed_enabled := false
        "Music bed disabled"
    end
)

server.register(
    "bed.volume",
    fun(v) -> begin
        bed_volume := float_of_string(v)
        "Music bed volume set to #{v}"
    end
)

server.register(
    "bed.duck_level",
    fun(v) -> begin
        bed_ducking_level := float_of_string(v)
        "Ducking level set to #{v}"
    end
)

server.register(
    "bed.status",
    fun(_) -> begin
        "enabled=#{!bed_enabled}, volume=#{!bed_volume}, duck_level=#{!bed_ducking_level}"
    end
)

# ========== TELNET COMMANDS - DUCKING CONTROL ==========

server.register(
    "duck.on",
    fun(_) -> begin
        ducking_active := true
        "Ducking activated"
    end
)

server.register(
    "duck.off",
    fun(_) -> begin
        ducking_active := false
        "Ducking deactivated"
    end
)

server.register(
    "duck.status",
    fun(_) -> begin
        "active=#{!ducking_active}"
    end
)

# ========== TELNET COMMANDS - INSTANT JINGLE CONTROL ==========

server.register(
    "jingle.play",
    fun(uri) -> begin
        instant_jingle_queue.push(request.create(uri))
        "Instant jingle queued: #{uri}"
    end
)

server.register(
    "jingle.volume",
    fun(v) -> begin
        jingle_volume := float_of_string(v)
        "Jingle volume set to #{v}"
    end
)

# ========== TELNET COMMANDS - MODERATION STATUS ==========

server.register(
    "moderation.status",
    fun(_) -> begin
        "bed_enabled=#{!bed_enabled}, ducking=#{!ducking_active}, bed_vol=#{!bed_volume}, duck_level=#{!bed_ducking_level}, jingle_vol=#{!jingle_volume}, mic_enabled=#{!mic_enabled}, mic_vol=#{!mic_volume}, mic_auto_duck=#{!mic_auto_duck}"
    end
)

# ========== TELNET COMMANDS - CROSSFADE CONTROL ==========

server.register(
    "crossfade.reload",
    fun(_) -> begin
        load_crossfade_settings()
        "Crossfade settings reloaded"
    end
)

server.register(
    "crossfade.music_fade_in",
    fun(v) -> begin
        crossfade_music_fade_in := float_of_string(default=0.5, v)
        "Music fade-in set to #{v}s"
    end
)

server.register(
    "crossfade.music_fade_out",
    fun(v) -> begin
        crossfade_music_fade_out := float_of_string(default=0.5, v)
        "Music fade-out set to #{v}s"
    end
)

server.register(
    "crossfade.jingle_fade_in",
    fun(v) -> begin
        crossfade_jingle_fade_in := float_of_string(default=0.0, v)
        "Jingle fade-in set to #{v}s"
    end
)

server.register(
    "crossfade.jingle_fade_out",
    fun(v) -> begin
        crossfade_jingle_fade_out := float_of_string(default=0.0, v)
        "Jingle fade-out set to #{v}s"
    end
)

server.register(
    "crossfade.moderation_fade_in",
    fun(v) -> begin
        crossfade_moderation_fade_in := float_of_string(default=0.0, v)
        "Moderation fade-in set to #{v}s"
    end
)

server.register(
    "crossfade.moderation_fade_out",
    fun(v) -> begin
        crossfade_moderation_fade_out := float_of_string(default=0.0, v)
        "Moderation fade-out set to #{v}s"
    end
)

server.register(
    "crossfade.status",
    fun(_) -> begin
        "music_in=#{!crossfade_music_fade_in}, music_out=#{!crossfade_music_fade_out}, jingle_in=#{!crossfade_jingle_fade_in}, jingle_out=#{!crossfade_jingle_fade_out}, mod_in=#{!crossfade_moderation_fade_in}, mod_out=#{!crossfade_moderation_fade_out}"
    end
)

# ========== TELNET COMMANDS - MICROPHONE CONTROL ==========

server.register(
    "mic.on",
    fun(_) -> begin
        mic_enabled := true
        # Auto-start ducking if enabled
        if !mic_auto_duck then
            ducking_active := true
        end
        # Auto-start music bed if enabled in settings
        if !mic_auto_duck then
            bed_enabled := true
        end
        "Microphone enabled"
    end
)

server.register(
    "mic.off",
    fun(_) -> begin
        mic_enabled := false
        # Auto-stop ducking
        if !mic_auto_duck then
            ducking_active := false
        end
        "Microphone disabled"
    end
)

server.register(
    "mic.volume",
    fun(v) -> begin
        mic_volume := float_of_string(v)
        "Microphone volume set to #{v}"
    end
)

server.register(
    "mic.auto_duck",
    fun(v) -> begin
        mic_auto_duck := (v == "true" or v == "1")
        "Microphone auto-duck set to #{v}"
    end
)

server.register(
    "mic.status",
    fun(_) -> begin
        "enabled=#{!mic_enabled}, volume=#{!mic_volume}, auto_duck=#{!mic_auto_duck}"
    end
)

# ========== CATEGORY INSERTION COMMANDS ==========

# These commands allow inserting random tracks from categories
server.register(
    "jingle",
    fun(_) -> begin
        # Insert a random jingle
        queue.push(request.create("/media/jingles"))
        "Jingle queued"
    end
)

server.register(
    "promo",
    fun(_) -> begin
        queue.push(request.create("/media/promos"))
        "Promo queued"
    end
)

server.register(
    "ad",
    fun(_) -> begin
        queue.push(request.create("/media/ads"))
        "Ad queued"
    end
)

server.register(
    "random_mod",
    fun(_) -> begin
        queue.push(request.create("/media/random-moderation"))
        "Random moderation queued"
    end
)

server.register(
    "planned_mod",
    fun(_) -> begin
        queue.push(request.create("/media/planned-moderation"))
        "Planned moderation queued"
    end
)
