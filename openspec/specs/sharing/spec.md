## Participant <-> Host Sharing: files and text

### Requirement: File upload pipeline delivers to daemon session folder
When a participant uploads a file, the system SHALL complete the delivery pipeline: Railway stores the file temporarily, notifies the daemon via WS, the daemon downloads the file to `{session_folder}/uploads/`, and Railway deletes the temp file after daemon confirmation.

#### Scenario: Successful end-to-end upload
- **WHEN** a participant uploads a file (≤ 100 MB) via `/api/upload`
- **THEN** Railway stores the file, sends `file_ready_for_download` WS message to the daemon with `file_id`, `filename`, `size`, and `download_url`
- **THEN** the daemon downloads the file to `{session_folder}/uploads/{filename}` and calls `POST /api/upload/{file_id}/ack` with `{"disk_path": "<abs_path>"}`
- **THEN** daemon stores `disk_path` and file indicator metadata in active daemon session state for host resume/reconnect
- **THEN** Railway broadcasts `file_uploaded` host WS message with `uuid`, `filename`, `size`, and `disk_path`
- **THEN** Railway deletes the temporary file

#### Scenario: File exceeds 100 MB
- **WHEN** a participant attempts to upload a file larger than 100 MB
- **THEN** Railway SHALL reject the request with HTTP 413 before storing the file
