# Edge-case coverage

Spec section 9 asks for every row to have an automated test or a logged manual
check. This file is that log. Test names are under `tests/`; run them with
`uv run pytest -q`. Manual checks were run on Arch Linux, Hyprland, PipeWire,
on the date shown, against the commit that was `main` at the time.

When you add a row to the spec, or change how one is handled, update its line
here in the same commit.

## 9.1 Session and input

| Scenario | Covered by |
| --- | --- |
| No speech at all | `test_daemon.py::test_silent_session_reports_no_speech`, `::test_whitespace_only_transcript_counts_as_no_speech`, `::test_the_no_speech_message_stays_up_long_enough_to_read` |
| Very short utterance | `test_daemon_cleanup.py::test_a_short_session_skips_the_llm`, `test_scheduler.py::test_a_short_session_skips_the_llm` |
| Very long dictation | `test_daemon.py::test_max_duration_finalizes_the_session`, `::test_max_duration_notes_the_limit_on_the_overlay` |
| Cancel | `test_daemon.py::test_cancel_injects_nothing`, `::test_capture_is_released_on_cancel`, `test_daemon_cleanup.py::test_a_cancel_during_the_llm_injects_nothing` |
| Start pressed while finalizing | `test_state.py::test_start_is_ignored_while_finalizing` |
| Double press | `test_state.py::test_double_press_within_debounce_is_one_command`, `test_daemon.py::test_debounce_still_applies_through_the_daemon` |
| Suspend or resume mid-session | `test_suspend.py` (4 tests), `test_daemon.py::test_a_suspend_mid_session_cancels_it_and_injects_nothing`. Detection is the boot-time/monotonic gap, not logind `PrepareForSleep`: no D-Bus dependency, same result. |
| Non-English speech | Out of scope per the spec; the guardrail and fallback tests in 9.3 bound the damage. |

## 9.2 Audio and STT

| Scenario | Covered by |
| --- | --- |
| No mic or device unplugged | `test_daemon.py::test_microphone_failure_is_reported_and_releases_the_machine`, `test_audio.py::test_a_stream_that_ends_while_recording_marks_the_capture_failed`, `::test_a_new_session_after_device_loss_opens_a_fresh_stream` |
| PipeWire restarted mid-session | `test_audio.py::test_a_stream_that_stops_delivering_marks_the_capture_failed`, `::test_releasing_a_lost_stream_does_not_wait_for_it`, `::test_a_slow_stop_that_finishes_within_the_grace_is_not_stuck` (a stop that finishes within the grace period does not restart the daemon), `test_daemon.py::test_a_lost_microphone_injects_the_text_so_far_and_notifies`, `::test_a_lost_microphone_with_nothing_heard_injects_nothing`. Manual, 2026-09-27: `systemctl --user restart pipewire` during a session; the daemon logged the lost mic within a second, returned to idle, answered `flowctl status` at once, and the next session recorded normally. |
| Mic held while idle (ADR 0015) | `test_audio.py::test_stopping_a_session_releases_portaudio`, `::test_portaudio_is_kept_while_an_abandoned_stream_may_still_be_stopping`, `::test_a_stop_still_running_past_the_grace_is_stuck`, `::test_a_failed_open_releases_portaudio`, `::test_a_stream_that_fails_to_start_is_closed_and_portaudio_released`, `test_daemon.py::test_an_idle_daemon_with_a_stuck_microphone_exits_to_be_restarted`, `::test_a_stuck_microphone_waits_for_the_session_to_finish`, `test_idle_check.py`. Manual, 2026-09-29: after start, a toggle/toggle session and a toggle/cancel, `scripts/idle_check.py` reported `audio: no PipeWire clients` and PASS each time; the daemon log showed `mic device: default (ALSA)` and `mic closed`. `pw-record` recorded a non-empty file both while flowd was idle and during an active session. |
| Mic busy or permission denied | `test_daemon.py::test_microphone_failure_is_reported_and_releases_the_machine`: one notification with the error, no retry until the next `start`. |
| STT falling behind real time | `test_daemon.py::test_stt_falling_behind_warns_with_cpu_load_and_drops_nothing` |
| STT model fails to load | `test_main.py::test_an_stt_model_that_fails_to_load_exits_non_zero_with_a_message` (exit 4). Manual, 2026-09-27: under `flowd.service`, `kill -9` was restarted by systemd (`NRestarts=1`). |
| Model hash mismatch | `test_models_lock.py::test_reports_hash_mismatch`, `::test_a_file_that_no_longer_matches_its_pin_is_refused` (exit 2, which `flowd.service` does not restart) |

## 9.3 LLM

| Scenario | Covered by |
| --- | --- |
| `llama-server` down | `test_cleanup.py::test_two_connect_errors_mark_the_llm_down`, `::test_a_healthy_probe_brings_the_llm_back`, `test_daemon_cleanup.py::test_a_down_llm_notifies_once_per_session`. Manual, 2026-09-27: `flowd --replay` with the server stopped fell back with `ConnectError`. |
| Chunk request times out | `test_cleanup.py::test_a_slow_server_times_out_without_counting_as_down`, `test_daemon_cleanup.py::test_a_timeout_falls_back_and_says_why` |
| Final chunk slow | `test_scheduler.py::test_the_flush_deadline_falls_back_whatever_is_unresolved`, `test_daemon_cleanup.py::test_a_model_that_never_answers_after_release_is_bounded_by_the_final_timeout` |
| Output fails guardrails | `test_guardrails.py::test_each_check_rejects_its_failure`, `test_daemon_cleanup.py::test_a_guardrail_rejection_falls_back_and_records_the_check` |
| Stale result after a merge | `test_scheduler.py::test_a_result_for_a_chunk_merged_away_is_discarded` |
| Correction cue in the first chunk | `test_scheduler.py::test_a_correction_cue_in_the_first_chunk_is_cleaned_without_a_merge` |
| Correction cue while previous is in flight | `test_scheduler.py::test_a_cue_waits_for_an_inflight_chunk_then_merges` |

## 9.4 Injection and desktop

| Scenario | Covered by |
| --- | --- |
| Focus changed during dictation | `test_daemon_cleanup.py::test_the_app_is_read_once_at_start`: the mode is chosen at start; the paste goes to whatever has focus at release. |
| No text field focused | `test_daemon.py::test_last_returns_previous_text_after_failed_injection`, `test_flowctl.py::test_last_prints_bare_text`. Not detectable, so the guarantee is that `flowctl last` still has the text. |
| Clipboard holds non-text data | `test_inject.py::test_clipboard_refuses_when_clipboard_holds_an_image` |
| Clipboard tool missing | `test_inject.py::test_clipboard_declines_when_the_paste_tool_is_missing`, `::test_falls_through_to_next_backend_on_failure` |
| Target is a terminal | `test_inject.py::test_terminal_uses_ctrl_shift_v`, `test_context.py::test_detect_maps_the_mode_and_flags_terminals` |
| Unicode that `xdotool type` mangles | `test_inject.py::test_non_ascii_text_prefers_the_clipboard_on_x11` |
| `ydotool` without `ydotoold` | `test_inject.py::test_ydotool_needs_the_ydotoold_socket`; setup is in the README. |
| Password field | Not detectable; documented in the README. `test_metrics.py::test_record_excludes_transcript_by_default`, `test_daemon.py::test_transcripts_are_not_logged_by_default` |

## 9.5 Process and overlay

| Scenario | Covered by |
| --- | --- |
| Second daemon started | `test_control.py::test_second_daemon_refuses_to_start`, `::test_busy_daemon_still_blocks_a_second_daemon`. Manual, 2026-09-27: a second `flowd` printed "already running" and exited 1. |
| Stale socket file | `test_control.py::test_stale_socket_is_removed_and_rebound` |
| Overlay crashes | `test_overlay_ipc.py::test_dead_child_is_respawned_on_next_show`, `::test_broken_pipe_is_swallowed`. Manual, 2026-09-27: killing the overlay mid-session left dictation working, and the next session respawned it. |
| Overlay would take focus | `test_overlay_process.py::test_overlay_disables_itself_when_layer_shell_is_unavailable`, `::test_overlay_becomes_a_layer_surface_that_refuses_focus` |
| `flowd-ui` would take focus (ADR 0013) | Pending. Manual: click the indicator and drag it on Hyprland, Sway, KDE and X11; the paste still lands in the original app. GNOME Wayland disables `flowd-ui` with a logged reason. |
| Settings API reached from another origin (ADR 0014) | Pending: tests for a missing or wrong token, a foreign `Host`, a foreign `Origin`, and a stale etag (`409`). |
| Config invalid on reload | `test_daemon.py::test_reload_with_bad_config_keeps_old`, `test_config.py::test_reload_keeps_old_config_on_error`. Manual, 2026-09-27: a bad `block_ms` was rejected by `flowctl reload` and the old config stayed. |

## Resource budget (spec 12)

`scripts/idle_check.py` measures idle anonymous memory and CPU across the
daemon, the overlay and `llama-server`. Manual, 2026-09-27, 60 s idle:
455 MB anon (budget 900), 0.33 % CPU (budget 1 %). That was before ADR 0011
added Parakeet; the budget is now 1,600 MB, and the daemon alone measured
about 1,140 MB anon idle with both models loaded (2026-09-28). The 24 h soak is
`scripts/idle_check.py --soak 24`; record its result here when it finishes.
