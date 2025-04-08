import os
import requests # This import seems unused now, consider removing if not needed elsewhere
import json   # This import seems unused now, consider removing if not needed elsewhere
import re
from github import Github
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from google import genai # Import the library

# --- Removed top-level client initialization and example call ---

def get_changed_files(pr):
    """Fetches changed TypeScript files from a Pull Request."""
    changed_files = []
    for file in pr.get_files():
        # Only consider TS files that were added, modified, or renamed
        if file.filename.endswith(('.ts', '.tsx', '.js', '.jsx', '.py', '.md')) and file.status in ['added', 'modified', 'renamed']:
            changed_files.append({
                'filename': file.filename,
                'patch': file.patch or "", # Ensure patch is not None
                'status': file.status,
            })
    return changed_files

def get_file_content(repo, file_path, ref):
    """Gets the decoded content of a file from the repository at a specific ref."""
    try:
        content = repo.get_contents(file_path, ref=ref)
        return content.decoded_content.decode('utf-8')
    except Exception as e:
        print(f"Error getting content for {file_path} at ref {ref}: {e}")
        return None # Return None or empty string to handle errors

def search_file(repo, file_obj, changed_files_set, changed_filenames_map, ref):
    """
    Searches a single file for references to changed file basenames.
    Optimized to use sets and precomputed basenames.
    """
    if file_obj.type == 'file' and file_obj.name.endswith(('.ts', '.tsx', '.js', '.jsx', '.py', '.md')): # Expanded file types slightly
        content = get_file_content(repo, file_obj.path, ref)
        if content is None: # Skip if content couldn't be fetched
            return None, set()

        related_to_changed = set()
        # Check if any changed filename (without extension) is mentioned in the content
        for changed_basename, original_filename in changed_filenames_map.items():
            # Use word boundaries (\b) to avoid partial matches (e.g., 'myVar' matching 'myVariable')
            if re.search(r'\b' + re.escape(changed_basename) + r'\b', content):
                related_to_changed.add(original_filename)

        if related_to_changed:
            return file_obj.path, related_to_changed
    return None, set()

def find_related_files(repo, changed_files, ref):
    """Finds files in the repository that might be related to the changed files."""
    related_files_map = defaultdict(set)
    if not changed_files:
        return related_files_map # Return empty if no changed files

    # Create a set of changed filenames for quick lookups
    changed_files_set = {f['filename'] for f in changed_files}
    # Create a map of base filenames (no ext) to original filenames for searching
    changed_filenames_map = {
        os.path.splitext(os.path.basename(f['filename']))[0]: f['filename']
        for f in changed_files
    }

    # --- Efficient Directory Traversal ---
    items_to_process = repo.get_contents('', ref=ref)
    files_to_scan = []

    while items_to_process:
        item = items_to_process.pop(0)
        if item.type == 'dir':
            # Add directory contents to the processing list (can be slow for large repos)
            # Consider limiting depth or skipping certain dirs (like node_modules) if needed
            if item.name not in ['node_modules', '.git', 'dist', 'build']: # Example exclusions
                 try:
                    items_to_process.extend(repo.get_contents(item.path, ref=ref))
                 except Exception as e:
                     print(f"Warning: Could not list contents of {item.path}: {e}")
        elif item.type == 'file':
            # Add file to the list to be scanned if it's not one of the changed files
            if item.path not in changed_files_set:
                files_to_scan.append(item)
    # -------------------------------------

    print(f"Scanning {len(files_to_scan)} files for relationships...")

    # Use ThreadPoolExecutor for parallel scanning
    with ThreadPoolExecutor(max_workers=10) as executor:
        # Pass the necessary precomputed sets/maps to the search function
        future_to_filepath = {
            executor.submit(search_file, repo, file_obj, changed_files_set, changed_filenames_map, ref): file_obj.path
            for file_obj in files_to_scan
        }

        for future in as_completed(future_to_filepath):
            try:
                scanned_file_path, related_to_which_changed = future.result()
                if scanned_file_path and related_to_which_changed:
                    for changed_file_origin in related_to_which_changed:
                        related_files_map[changed_file_origin].add(scanned_file_path)
            except Exception as e:
                 filepath = future_to_filepath[future]
                 print(f"Error processing file {filepath}: {e}")


    print("Finished finding related files.")
    return related_files_map


def call_gemini_api(changes, related_files_map, api_key):
    """
    Generates a code review using the Gemini API based on changes and related files.

    Args:
        changes (list): A list of dictionaries, each representing a changed file.
                        Expected keys: 'filename', 'status', 'patch', 'full_content'.
        related_files_map (defaultdict): A map where keys are changed filenames and
                                       values are sets of related file paths.
        api_key (str): The API key for Google Generative AI.

    Returns:
        str: The generated code review text, or an error message.
    """

    # --- Construct the Prompt (System Instruction) ---
    system_instruction = (
        "당신은 경험 많은 시니어 소프트웨어 엔지니어입니다. 주어진 코드 변경사항과 관련 파일 정보를 바탕으로 통합적인 코드 리뷰를 수행해주세요.\n\n"
        "리뷰 지침:\n"
        "1. **통합적 관점:** 개별 파일 리뷰 대신 전체 변경사항에 대한 일관된 관점을 유지하세요.\n"
        "2. **핵심 집중:** 가장 중요하고 영향력 있는 문제점(버그, 성능, 보안, 설계) 또는 개선 사항에 초점을 맞추세요.\n"
        "3. **구체적 제안:** 발견된 각 주요 이슈에 대해 명확한 설명과 실행 가능한 개선 방안을 제시하세요.\n"
        "4. **코드 예시:** 개선 제안을 뒷받침하는 간결하고 정확한 코드 예시를 포함하세요. (제공된 코드 맥락 내에서)\n"
        "5. **사소함 지양:** 단순 스타일, 명명 규칙, 개인적 선호도 등 사소한 지적은 피하세요.\n"
        "6. **변경 사항 중심:** 리뷰는 제출된 '변경된 부분(patch)'과 '전체 내용(full_content)'에 기반해야 합니다. 이미 존재하는 코드의 문제를 지적하기보다 변경으로 인해 발생하거나 수정되어야 할 부분에 집중하세요.\n"
        "7. **긍정적 피드백:** 잘된 점이나 이전 리뷰에서 개선된 사항(예: 중복 제거 함수 생성)이 있다면 간략히 언급하세요.\n"
        "8. **영향 분석:** 변경된 파일이 '관련된 파일들' 목록에 있는 다른 파일들에 미칠 수 있는 잠재적 영향(예: 인터페이스 변경, 부수 효과)을 분석하고 언급하세요.\n"
        "9. **간결성:** 전체 리뷰는 명확하고 간결하게 작성하세요.\n\n"
        "리뷰 형식:\n"
        "```markdown\n"
        "## 코드 리뷰 요약\n\n"
        "**개선된 사항:**\n"
        "- [개선된 부분이나 잘된 점에 대한 긍정적 언급 (해당하는 경우)]\n\n"
        "**주요 검토 항목:** (심각한 문제가 없는 경우 생략 가능)\n"
        "1. **[문제점 요약]**\n"
        "   - **설명:** [문제점에 대한 상세 설명]\n"
        "   - **제안:** [개선 방안]\n"
        "   ```typescript\n"
        "   // 수정 제안 코드 예시\n"
        "   ```\n"
        "2. ...\n\n"
        "**관련 파일 영향 분석:**\n"
        "- [변경된 파일이 관련 파일들에 미칠 수 있는 잠재적 영향 요약]\n"
        "  - 예: `{changed_file}`의 변경으로 인해 `{related_file}`의 특정 함수 동작이 변경될 수 있습니다.\n\n"
        "**전반적인 의견:**\n"
        "[1-2 문장의 전체적인 평가 및 요약]\n"
        "```\n\n"
        "--- 변경된 파일 정보 ---\n"
    )

    for file_info in changes:
        system_instruction += f"\n파일명: {file_info['filename']} (상태: {file_info['status']})\n"
        system_instruction += f"변경 내용 (Patch):\n```diff\n{file_info['patch']}\n```\n"
        # Optionally include full content if context is crucial and token limits allow
        # Be mindful of large files potentially exceeding token limits
        # system_instruction += f"전체 내용:\n```typescript\n{file_info['full_content'][:4000]}\n```\n" # Truncate if necessary
        system_instruction += "---\n"


    system_instruction += "\n--- 관련된 파일 목록 ---\n"
    if related_files_map:
        for changed_file, related_set in related_files_map.items():
            if related_set: # Only list if there are related files found
                system_instruction += f"- `{changed_file}`와(과) 연관 가능성 있는 파일:\n"
                for related_file in sorted(list(related_set)): # Sort for consistent output
                    system_instruction += f"  - `{related_file}`\n"
    else:
        system_instruction += "관련된 파일이 발견되지 않았습니다.\n"
    # --------------------------------------------------

    # --- Prepare the User Prompt for Gemini ---
    user_prompt = (
        "위에 제공된 시스템 지침, 변경된 파일 정보, 관련 파일 목록을 바탕으로, "
        "통합적이고 실행 가능한 코드 리뷰를 생성해주세요. "
        "가장 중요한 항목에 집중하고, 구체적인 코드 예시를 포함하여 제안해주세요."
    )
    # ------------------------------------------

    # --- Make the API Call ---
    try:
        client = genai.Client(api_key=os.environ['GEMINI_API_KEY'])

        response = client.models.generate_content(
            model="gemini-2.5-pro-exp-03-25",
            contents=[system_instruction + user_prompt]
        )

        return response.text
    except Exception as e:
        print(f"Error calling Gemini API: {e}")
        # Provide more context if possible, e.g., if it's an API key issue or quota issue
        return f"Gemini API 호출 중 오류 발생: {e}"
    # -------------------------


def main():
    # --- Get Environment Variables ---
    github_token = os.environ.get('GITHUB_TOKEN')
    repo_name = os.environ.get('GITHUB_REPOSITORY')
    pr_number_str = os.environ.get('PR_NUMBER')
    gemini_api_key = os.environ.get('GEMINI_API_KEY') # Get Gemini key

    if not all([github_token, repo_name, pr_number_str, gemini_api_key]):
        print("Error: Missing required environment variables (GITHUB_TOKEN, GITHUB_REPOSITORY, PR_NUMBER, GEMINI_API_KEY)")
        exit(1)

    try:
        pr_number = int(pr_number_str)
    except ValueError:
        print(f"Error: Invalid PR_NUMBER: {pr_number_str}")
        exit(1)
    # ---------------------------------

    print(f"Processing PR #{pr_number} in repository {repo_name}")

    try:
        g = Github(github_token)
        repo = g.get_repo(repo_name)
        pr = repo.get_pull(pr_number)

        print("Fetching changed files...")
        changed_files = get_changed_files(pr)

        if not changed_files:
            print("No relevant (.ts, .js, .py, .tsx, .jsx) files changed in this PR. Exiting.")
            # Optionally post a comment indicating no review needed
            # pr.create_issue_comment("리뷰할 TypeScript 변경 사항이 없습니다.")
            exit(0)

        print(f"Found {len(changed_files)} changed TypeScript files.")
        changes_with_content = []
        print("Fetching full content for changed files...")
        for file_info in changed_files:
            print(f"  - Fetching {file_info['filename']}")
            full_content = get_file_content(repo, file_info['filename'], pr.head.sha)
            if full_content is not None:
                 file_info['full_content'] = full_content
                 changes_with_content.append(file_info)
            else:
                 print(f"  - Warning: Could not fetch content for {file_info['filename']}")
                 # Decide how to handle files where content fetch fails
                 # Option 1: Skip the file
                 # Option 2: Proceed without full_content (Gemini might struggle)
                 # Let's skip it for now to ensure Gemini gets full context
                 # file_info['full_content'] = "" # Or provide empty string
                 # changes_with_content.append(file_info)


        if not changes_with_content:
             print("Could not fetch content for any changed files. Exiting.")
             exit(1)

        print("Finding related files...")
        # Pass only the files we successfully got content for
        related_files_map = find_related_files(repo, changes_with_content, pr.head.sha)

        print("Generating review using Gemini API...")
        # Pass the Gemini API key to the function
        review = call_gemini_api(changes_with_content, related_files_map, gemini_api_key)

        print("Posting review comment to PR...")
        # Update comment to mention Gemini
        pr.create_issue_comment(f"✨ **Gemini 코드 리뷰** ✨\n\n{review}")
        print("Review comment posted successfully.")

    except Exception as e:
        print(f"An error occurred during the process: {e}")
        # Optionally try to post an error comment to the PR
        try:
            if 'pr' in locals(): # Check if pr object exists
                pr.create_issue_comment(f"코드 리뷰 봇 실행 중 오류가 발생했습니다: {e}")
        except Exception as comment_e:
            print(f"Failed to post error comment to PR: {comment_e}")
        exit(1)

if __name__ == "__main__":
    main()