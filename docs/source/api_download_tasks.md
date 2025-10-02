# API and Media Download Task Breakdown

## 1. Metadata Retrieval Endpoint
- [ ] Create a FastAPI (or similar) service module at `AdDownloader/api/service.py` exposing a POST endpoint.
- [ ] Define request schema accepting `access_token`, optional filters (`ad_reached_countries`, date range), and identifiers (`page_ids` or `ad_library_ids`).
- [ ] Update `AdDownloader/adlib_api.py` so `add_parameters` can ingest page IDs provided directly as lists instead of requiring Excel files.
- [ ] Map submitted Ad Library IDs onto the query parameters expected by Meta's Ad Library (for example, using search terms) before invoking `add_parameters`.
- [ ] Call `start_download` to execute the query, handle pagination, and capture the processed DataFrame.
- [ ] Serialize the resulting records with `DataFrame.to_dict(orient="records")` and structure the API response with project metadata.

## 2. Creative Download Flow
- [ ] Refresh each ad's `ad_snapshot_url` with the latest access token via `AdDownloader.helpers.update_access_token`.
- [ ] Determine which ads to download (all or a caller-specified subset).
- [ ] Invoke `AdDownloader.media_download.start_media_download` with the project name, desired count, and updated DataFrame to save images/videos.
- [ ] Collect the success/failure counts and asset paths from the downloader for inclusion in the API response.
- [ ] Ensure Selenium drivers and loggers are shut down after each request.
- [ ] Implement error handling that returns informative responses on failure.
