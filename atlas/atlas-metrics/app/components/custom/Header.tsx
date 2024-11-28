import { AuthButton } from "@components/custom/AuthButton";

export function Header() {
  return (
    <header className="mb-5">
      <div className="grid grid-flow-col grid-cols-2 items-center justify-items-end gap-5">
        <h1 className="scroll-m-20 justify-self-start text-4xl font-extrabold tracking-tight lg:text-5xl">
          Atlas Metrics
        </h1>
        <AuthButton />
      </div>
    </header>
  );
}
