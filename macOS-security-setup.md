# macOS Security Prompt Guide

## The problem

When you double-click "**Start Legal Anonymizer.command**", macOS shows a prompt like this:

> **"Start Legal Anonymizer.command" cannot be opened**
>
> Apple cannot verify that "Start Legal Anonymizer.command" is free of malware that could harm your Mac or compromise your privacy.

This is macOS's normal security mechanism (Gatekeeper), which blocks every script not downloaded from the App Store. This tool runs entirely locally; it does not connect to the internet and does not upload any data.

---

## How to fix it

### Method 1: allow it through System Settings (recommended)

1. **When the security prompt appears, click "Done"** (do not click "Move to Trash")

2. **Open System Settings**
   - Click the Apple menu in the top-left corner of the screen → **System Settings**

3. **Go to "Privacy & Security"**
   - Select **Privacy & Security** in the left sidebar

4. **Find the blocked-app prompt and allow it**
   - Scroll down the page; in the "Security" section at the bottom you will see:
   > "Start Legal Anonymizer.command" was blocked from use because it is not from an identified developer.
   - Click **"Open Anyway"** on the right

5. **Confirm with your password**
   - macOS will ask for your computer password or Touch ID verification

6. **Double-click to run again**
   - Go back to the folder and double-click "Start Legal Anonymizer.command" again
   - This time the dialog will show an **"Open"** button; click it
   - You will not see the prompt again on later runs

---

### Method 2: open with right-click

1. **Control-click the file** (or two-finger tap on the trackpad)
2. Choose **"Open"** from the context menu
3. When the security prompt appears, click the **"Open"** button

> Note: on macOS Sequoia (15.0+) this method may still be blocked. If so, use Method 1 or Method 3.

---

### Method 3: remove the restriction via Terminal (permanent)

If the methods above do not work, you can remove the file's quarantine flag through Terminal:

1. **Open Terminal**
   - Press `Command + Space` to open Spotlight, type **Terminal**, and press Return

2. **Run the following command** (just copy and paste):

   If the tool is in the "Downloads" folder:
   ```
   xattr -cr ~/Downloads/legal-anonymizer
   ```

   If it is elsewhere, replace the path with the actual folder path:
   ```
   xattr -cr /your/actual/path/legal-anonymizer
   ```

   > `xattr -cr` removes the "downloaded from the internet" quarantine flag from all files in the folder, and nothing more. It does not modify file contents.

3. **Double-click again and it will run normally**

---

### Method 4: launch directly from Terminal (no security settings needed)

If you would rather not change any system settings, you can launch directly from Terminal:

1. **Open Terminal** (as above)

2. **Run the following commands**:
   ```
   cd /your/actual/path/legal-anonymizer
   python3 web_app.py
   ```

3. **Open your browser to** http://127.0.0.1:8080

---

## Why does macOS block it?

- macOS automatically adds a "quarantine attribute" to files downloaded from the internet
- Scripts without an Apple developer signature are blocked by Gatekeeper
- This is Apple's security policy and does not mean the file is faulty
- This tool is an open-source script that runs entirely locally; all data processing happens on your computer, and nothing is uploaded

---

## FAQ

**Q: What if I clicked "Move to Trash"?**
A: Open the Trash, right-click the file, and choose "Put Back" to restore it.

**Q: I can't find the "Open Anyway" option in System Settings.**
A: It only appears after you try to open the blocked file once. If you still can't find it, use Method 3 (the Terminal command).

**Q: Do I have to confirm every time I open it?**
A: No. After you allow it the first time, double-clicking will run it directly afterward.
