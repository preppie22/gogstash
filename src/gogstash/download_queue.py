from gogstash import library_db
from gogstash import settings

def _platform_helper(platforms: list[str]) -> list[str]:
    platform_filter = []
    if 'Linux' in platforms:
        platform_filter.append('linux')
    if 'Windows' in platforms:
        platform_filter.append('windows')
    if 'MacOS' in platforms:
        platform_filter.append('mac')
    return platform_filter

def generate_download_list(product_ids: tuple[int]):
    if not product_ids:
        return
    downloadables = library_db.get_downloadables(product_ids)
    bonus_content = settings.read_setting('bonus_content')
    platforms = _platform_helper(settings.read_setting('platform_filter'))
    patches = settings.read_setting('patches')
    files = []
    for item in downloadables:
        if not item['os'] in platforms and item['os']:
            continue
        file_info = {
            'directory': "",
            'file': item['file_id'],
            'os': item['os'],
            'size': item['file_size'],
            'downlink': item['downlink'],
        }
        if item['category'] == 'installers':
            file_info['directory'] = item['group_id']
        elif item['category'] == 'patches' and patches:
            file_info['directory'] = 'patches'
        elif item['category'] == 'bonus_content' and bonus_content:
            file_info['directory'] = 'bonus_content'
        else:
            continue
        files.append(file_info)
    return files

if __name__ == "__main__":
    file_list = generate_download_list((1929434313,))
    for item in file_list:
        print(item)