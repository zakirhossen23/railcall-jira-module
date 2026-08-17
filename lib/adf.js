"use strict";

/**
 * Atlassian Document Format (ADF) helpers.
 *
 * Jira Cloud stores rich-text fields (like `description`) as ADF documents:
 *   { type: "doc", version: 1, content: [...] }
 * These helpers convert plain text into ADF so callers don't have to know the
 * format, while still passing through hand-built ADF unchanged.
 */

/** @returns {object} an empty ADF doc */
function emptyAdfDoc() {
  return {
    type: "doc",
    version: 1,
    content: [],
  };
}

/**
 * Convert a description value into an ADF document.
 *
 * @param {string|object} value - plain text, or an ADF doc ({type:"doc"})
 * @returns {object} ADF document
 */
function toAdfDescription(value) {
  if (value === undefined || value === null) return emptyAdfDoc();

  // Already ADF — pass through untouched.
  if (typeof value === "object" && value.type === "doc") return value;

  if (typeof value === "string") {
    const paragraphs = value
      .split(/\n{2,}/) // blank-line separated paragraphs
      .map((p) => p.trim())
      .filter((p) => p.length > 0)
      .map((p) => ({
        type: "paragraph",
        content: [{ type: "text", text: p }],
      }));

    return {
      type: "doc",
      version: 1,
      content: paragraphs.length ? paragraphs : [{ type: "paragraph", content: [] }],
    };
  }

  throw new Error("description must be a string or an ADF document object ({ type: 'doc', ... })");
}

module.exports = { toAdfDescription, emptyAdfDoc };
