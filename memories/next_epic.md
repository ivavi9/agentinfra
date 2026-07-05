# Epic: Frontend Text Beautification & Markdown Rendering

This epic defines the requirements, design decisions, and implementation steps for introducing rich text and markdown parsing capabilities to the Stateful Copilot Agent chat interface.

## 1. Problem Statement
Currently, all response payloads from our multi-agent supervisor (e.g., capability lists, bulleted infrastructure statuses, technology comparisons) are rendered as plain text using CSS `white-space: pre-wrap`. Bold markdown elements (`**bold**`), bullet points (`* item`), headers (`### Title`), code fragments (`` `code` ``), and code blocks are displayed in raw, unparsed markdown format. This detracts from the "premium interface" aesthetic mandated by our rules.

## 2. Goals & Scope
- **Rich Parsing**: Automatically translate basic markdown structure in the agent's responses into corresponding structured React HTML components.
- **Supported Tokens**:
  - **Bold Text**: `**text**` ➔ `<strong>text</strong>`
  - **Headers**: `### Header 3`, `## Header 2`, `# Header 1` ➔ `<h3>`, `<h2>`, `<h1>`
  - **Inline Code**: `` `code` `` ➔ `<code class="inline-code">`
  - **Fenced Code Blocks**: ` ```lang code ``` ` ➔ `<pre><code class="block-code">` with language-specific wrapper support.
  - **Lists**: Bullet points (`*` or `-`) ➔ `<ul>` / `<li>` lists.
  - **Line Breaks**: Single and double newlines ➔ paragraph spacing.
- **No Heavy Libraries / Crash Risk**: Since React 19 is active in this project, installing heavy external markdown parsers can trigger React-version dependency conflicts during build time. We will implement a safe, custom, zero-dependency RegExp-based parser that maps markdown strings directly to React elements.

## 3. Design Decisions
- **Custom Tokenizer**: We will write a utility function `parseMarkdownText(text)` in the frontend. It will parse paragraphs and split text tokens using regular expressions, mapping them into safe JSX structures.
- **Aesthetic Styling**:
  - Code blocks will render with a dark translucent background (`rgba(0, 0, 0, 0.4)`), soft borders, outfit monospace styling, and copy-code helper support.
  - Inline code blocks will render with a subtle purple pill styling matching our theme colors.
  - Bullet points will be indented with modern dots and appropriate margins.

## 4. Task Breakdown
- [ ] Task 1: Create the markdown-to-JSX tokenizer function `parseMarkdownText(text)` in `frontend/src/App.jsx`.
- [ ] Task 2: Style the new HTML elements in `frontend/src/App.css` (custom margins, lists, code cards).
- [ ] Task 3: Update `renderMessageContent` in `App.jsx` to pass the `cleanContent` through the markdown renderer.
- [ ] Task 4: Verify the rich text rendering works in the browser and visually validate headers, lists, and code styling.
