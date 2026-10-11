from gogstash import paths


def test_log_files_live_in_their_own_folder(tmp_path):
    # The config folder holds settings, the token and the cache. The logs
    # get a room of their own instead of sprawling across the living room.
    for log_file in paths.LogFile:
        assert paths.log_file_path(log_file) == tmp_path / "logs" / log_file.value
