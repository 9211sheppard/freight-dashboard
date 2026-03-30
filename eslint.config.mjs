import js from "@eslint/js";
import globals from "globals";

export default [
  {
    ignores: [
      "static/bootstrap.bundle.min.js",
      "node_modules/**"
    ]
  },
  js.configs.recommended,
  {
    files: ["static/**/*.js"],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: "script",
      globals: {
        ...globals.browser,
        ...globals.serviceworker,
        bootstrap: "readonly"
      }
    },
    rules: {
      "no-unused-vars": ["error", { "args": "none", "caughtErrors": "none" }],
      "no-console": "off"
    }
  },
  {
    files: ["static/learn.js"],
    languageOptions: {
      globals: {
        ALL_QUOTES: "readonly",
        BOOKS: "readonly"
      }
    }
  }
];
