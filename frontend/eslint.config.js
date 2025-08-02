import js from "@eslint/js";
import globals from "globals";
import pluginVue from "eslint-plugin-vue";

export default [
  {
    // Ignore build artifacts and dependencies
    ignores: ["dist/**", "node_modules/**"],
  },

  // Apply JS recommended rules. This targets .js and .mjs files by default.
  js.configs.recommended,

  // Apply Vue essential rules. This targets .vue files and configures the correct parser.
  ...pluginVue.configs['flat/essential'],

  // Add global variables for all linted files.
  {
    languageOptions: {
      globals: {
        ...globals.browser,
        ...globals.node, // For config files like vite.config.js
      },
    },
  },
];
