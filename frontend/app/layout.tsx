import "./globals.css";

export const metadata = {
  title: "Isometric to MTO Generator",
  description: "Upload a piping isometric drawing and get an AI-generated Material Take-Off.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen text-slate-800">{children}</body>
    </html>
  );
}
