# Companion behaviour review and finish gates — 2 November 2026

Scope: native desktop companion and new browser-chat handoff. Native Assessment A only; no web/CDP detector was run. Current installed Mac inspected through native accessibility: old interface remains idle with Codex connected. New UI is a development candidate, not yet installed. Questions skipped: service targets (ChatGPT, Claude, Gemini), README destination and explicit wake-word opt-in were already answered by the user.

## Behaviour contract

1. **Wake-word opt-in:** distinguish Off, Listening for Hey Ambi, and In conversation. A persistent microphone control turns both detection and conversation off. Request OS permission in context and explain where audio is processed before enabling detection. This is the highest-priority implementation gap.
2. **Turn-taking:** immediate visible acknowledgement, optional short earcon, listening/speaking/working labels and matching mascot poses. Allow interruption when the actual audio engine supports it; Windows compatibility audio can mute capture during playback, so a persistent button must work without spoken interruption. Do not promise barge-in before platform testing.
3. **Progress:** expand the action panel on a new conversation/task, retain manual collapse, show observed actions, distinguish worker returned from independently verified success, and clear the activity tint on cancellation/disconnection.
4. **Control:** Stop task cancels further work; End conversation turns off voice. Keep both concepts clear, including any future wake-word armed state. Approval pauses use a distinct attention state.
5. **Recovery:** explain missing microphone/API/desktop access and expose a direct recovery action. Avoid endless no-input or no-match loops; after bounded reprompts return to an explicit ready/off state.
6. **Other chats:** show the chosen service and the exact draft. Copy/open is a user action, sending is reviewed in the destination. Existing account sign-ins belong to each service. Browser handoff does not establish conversation import, reply reading or autonomous cross-chat control.
7. **Presentation:** keep the larger organic mascot, selectable saved themes, reduced-motion/Still choice and strong transient task frame. An eventual LED should mirror these states while text and Stop remain available on screen.

These are an application of Apple privacy guidance, Amazon hands-free microphone controls, and Google voice turn-taking/error guidance, not a claim that one layout is universally best. Sources: https://developer.apple.com/design/human-interface-guidelines/privacy/ ; https://developer.amazon.com/en-US/alexa/voice-interoperability/design-guide/human-interface-design ; https://docs.cloud.google.com/dialogflow/cx/docs/concept/voice-agent-design ; https://developers.google.com/assistant/conversation-design/errors .

## Finish gates and evidence

| Gate | Current evidence | Required before calling complete |
| --- | --- | --- |
| New UI | Source/builds and labelled synthetic screenshots; scoped finish review ship | Install and exercise native host on both computers |
| Browser handoff | All three correct destination URLs opened in IAB;62 Windows UI tests/63 Mac UI tests, both production builds; Swift release with5 tests and Windows publish with24 policy/lifecycle checks | Native copy/open on Mac and Windows; authenticated service sessions |
| Full browser chat compatibility | Not implemented; no history/replies read, no auto-send | Supervised fresh fictional thread in each service; confirm correct tab/composer, draft, send boundary, response reading and cancellation |
| Wake word | Explicit preference recorded; no detector implemented | Local/cloud processing decision disclosed; opt-in/off, false activations, silence, self-wake, device switch, lock/sleep, interruption and restart tests |
| Voice/computer control | Original voice demo retained; previous reply-only/native frame checks are separate evidence | Real voice-to-Notepad task, saved-text readback, Stop and full-display frame cleanup on each platform |
| README media |12-second silent UI capture with synthetic state, no private desktop/history/key data | Push/readback and confirm rendered media |
| Distribution | Build candidates only | Mac notarization, Windows signing and per-user install/upgrade/uninstall acceptance; updates/recovery clearly documented |

Do not use automated tests, synthetic listening frames or URL opening as proof of live voice, real desktop input, or authenticated chat compatibility. Preserve existing platform audio engines and original installations until their replacements pass acceptance.
