// Vite loads `?raw` imports as plain strings. The specs that pin a
// stylesheet contract read the .scss source this way, because the unit-test
// environment applies no layout and the declarations themselves are the
// change under test.
declare module '*.scss?raw' {
  const content: string;
  export default content;
}
