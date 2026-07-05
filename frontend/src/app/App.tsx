import { QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import { RouterProvider } from "react-router-dom";

import { SelectionProvider } from "./SelectionContext";
import { ThemeProvider } from "./ThemeContext";
import { createQueryClient } from "./query-client";
import { createAppRouter } from "./router";

export function App() {
  const [queryClient] = useState(createQueryClient);
  const [router] = useState(createAppRouter);

  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <SelectionProvider>
          <RouterProvider router={router} />
        </SelectionProvider>
      </ThemeProvider>
    </QueryClientProvider>
  );
}
