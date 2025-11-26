import requests
import json
import os
import base64
import time
import ast 
from typing import List

# =========================================================================
# === 1. YAPILANDIRMA AYARLARI ============================================
# =========================================================================
GITHUB_TOKEN = "GITHUB TOKEN'INIZ"  
HEADERS = {
    "Authorization": f"token {GITHUB_TOKEN}",
    "Accept": "application/vnd.github.v3+json"
}

OUTPUT_DIR = "human_code_dataset"
TARGET_LICENSE = "mit"             
TARGET_LANGUAGE = "python"         
MAX_CODE_BLOCKS = 2500             
MAX_BLOCKS_PER_REPO = 50
# -------------------------------------------------------------------------

def check_rate_limit():
    """GitHub API rate limit kontrolü"""
    response = requests.get("https://api.github.com/rate_limit", headers=HEADERS)
    if response.status_code == 200:
        data = response.json()
        remaining = data['resources']['core']['remaining']
        print(f"\n[Rate Limit] Kalan: {remaining}")
        if remaining < 10:
            reset_time = data['resources']['core']['reset']
            wait_time = reset_time - time.time()
            print(f"Rate limit doldu. {wait_time/60:.1f} dakika bekleniyor...")
            time.sleep(wait_time + 10)

def github_search_repos(license_key: str, language: str, max_repos: int = 100) -> List[dict]:
    """
    Belirli lisans ve dile sahip popüler repoları arar.
    """
    print(f"GitHub'da {language} {license_key} lisanslı repolar aranıyor...")
    all_repos = []
    
    # API limiti: 1000 sonuç, sayfa başına max 100
    pages_needed = min(10, (max_repos + 99) // 100)
    
    for page in range(1, pages_needed + 1): 
        query = f"language:{language} license:{license_key} stars:>100"
        url = f"https://api.github.com/search/repositories?q={query}&sort=stars&per_page=100&page={page}"
        
        response = requests.get(url, headers=HEADERS)
        
        if response.status_code == 403:
            check_rate_limit()
            response = requests.get(url, headers=HEADERS)
            
        if response.status_code != 200:
            print(f"\nHATA: Repo arama başarısız. Kod: {response.status_code}, Sayfa: {page}")
            print(f"Yanıt: {response.text[:200]}")
            break
        
        repos = response.json().get("items", [])
        if not repos:
            print(f"\nSayfa {page}'de repo bulunamadı.")
            break
            
        all_repos.extend(repos)
        print(f"\rSayfa {page}/{pages_needed} - Toplam: {len(all_repos)} repo", end="")
        time.sleep(1)  # Rate limit için bekleme
        
    print()
    return all_repos

def get_default_branch(repo_full_name: str) -> str:
    """Repo'nun default branch'ini öğren"""
    url = f"https://api.github.com/repos/{repo_full_name}"
    response = requests.get(url, headers=HEADERS)
    if response.status_code == 200:
        return response.json().get("default_branch", "main")
    return "main"

def get_file_contents(repo_full_name: str, file_path: str) -> str | None:
    """Belirtilen dosyanın içeriğini çeker."""
    url = f"https://api.github.com/repos/{repo_full_name}/contents/{file_path}"
    
    try:
        response = requests.get(url, headers=HEADERS)
        if response.status_code == 200:
            data = response.json()
            if data.get("type") == "file" and "content" in data:
                content_b64 = data["content"]
                return base64.b64decode(content_b64).decode('utf-8', errors='ignore')
    except Exception as e:
        pass
        
    return None

def extract_code_blocks(code_content: str, lang: str = "python") -> List[str]:
    """AST kullanarak kodu anlamlı fonksiyon/sınıf bloklarına ayırır."""
    blocks = []
    
    if lang.lower() == 'python':
        try:
            tree = ast.parse(code_content)
        except:
            return []

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                start_line = node.lineno - 1
                end_line = node.end_lineno
                
                if end_line and end_line - start_line >= 3:
                    source_lines = code_content.splitlines()
                    block_code = "\n".join(source_lines[start_line:end_line])
                    blocks.append(block_code.strip())
    
    if not blocks and len(code_content.split('\n')) >= 10: 
        blocks = [code_content.strip()]
        
    return blocks

def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    check_rate_limit()
    
    # Repoları ara
    repos = github_search_repos(TARGET_LICENSE, TARGET_LANGUAGE, max_repos=100)
    
    if not repos:
        print("HATA: Hiç repo bulunamadı!")
        return
    
    collected_count = 0
    file_index = 1
    
    print(f"\n{len(repos)} repo bulundu. Hedef: {MAX_CODE_BLOCKS} kod bloğu\n")

    for repo in repos:
        if collected_count >= MAX_CODE_BLOCKS:
            break
            
        repo_name = repo["full_name"]
        current_repo_blocks = 0
        
        print(f"\n[{collected_count}/{MAX_CODE_BLOCKS}] İşleniyor: {repo_name}")
        
        # Default branch'i öğren
        default_branch = get_default_branch(repo_name)
        
        try:
            # Repo ağacını al
            tree_url = f"https://api.github.com/repos/{repo_name}/git/trees/{default_branch}?recursive=1"
            tree_response = requests.get(tree_url, headers=HEADERS)
            
            if tree_response.status_code == 403:
                check_rate_limit()
                tree_response = requests.get(tree_url, headers=HEADERS)
            
            if tree_response.status_code != 200:
                print(f"  ⚠ Tree alınamadı (kod: {tree_response.status_code})")
                continue
            
            tree_data = tree_response.json()
            
            if "tree" not in tree_data:
                print(f"  ⚠ Tree verisi bulunamadı")
                continue
                
            # Python dosyalarını filtrele
            py_files = [
                item["path"] for item in tree_data["tree"]
                if item["type"] == "blob" and item["path"].endswith(".py")
            ]
            
            print(f"  → {len(py_files)} Python dosyası bulundu")
            
            # Dosyaları işle
            for file_path in py_files[:30]:  # Her repodan max 30 dosya
                if collected_count >= MAX_CODE_BLOCKS or current_repo_blocks >= MAX_BLOCKS_PER_REPO:
                    break

                code_content = get_file_contents(repo_name, file_path)
                
                if code_content:
                    code_blocks = extract_code_blocks(code_content, TARGET_LANGUAGE)
                    
                    for block in code_blocks:
                        if collected_count >= MAX_CODE_BLOCKS or current_repo_blocks >= MAX_BLOCKS_PER_REPO:
                            break
                        
                        data = {
                            "code": block,
                            "source": f"github_repo:{repo_name}",
                            "file": file_path,
                            "license": TARGET_LICENSE.upper(),
                            "language": TARGET_LANGUAGE
                        }
                        
                        filename = os.path.join(OUTPUT_DIR, f"human_{file_index}.json")
                        with open(filename, 'w', encoding='utf-8') as f:
                            json.dump(data, f, indent=4, ensure_ascii=False)
                        
                        collected_count += 1
                        current_repo_blocks += 1
                        file_index += 1
                
                time.sleep(0.1)  # Rate limit için küçük bekleme
            
            print(f"  ✓ {current_repo_blocks} blok toplandı")
            
        except Exception as e:
            print(f"  ✗ Hata: {str(e)[:100]}")
            continue

    print(f"\n{'='*60}")
    print(f"TAMAMLANDI!")
    print(f"Toplam {collected_count} kod bloğu '{OUTPUT_DIR}' klasörüne kaydedildi.")
    print(f"{'='*60}")

if __name__ == "__main__":
    main()