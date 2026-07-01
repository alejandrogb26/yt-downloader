/* eslint-disable react-refresh/only-export-components */
import { createContext, useContext, useState, type ReactNode } from "react";

type SelectionContextValue = {
  selectedProfileId: string;
  setSelectedProfileId: (profileId: string) => void;
  destinationPath: string;
  setDestinationPath: (path: string) => void;
};

const SelectionContext = createContext<SelectionContextValue | null>(null);

export function SelectionProvider({ children }: { children: ReactNode }) {
  const [selectedProfileId, setSelectedProfileId] = useState("");
  const [destinationPath, setDestinationPath] = useState("");

  return (
    <SelectionContext.Provider
      value={{
        selectedProfileId,
        setSelectedProfileId,
        destinationPath,
        setDestinationPath,
      }}
    >
      {children}
    </SelectionContext.Provider>
  );
}

export function useSelection(): SelectionContextValue {
  const value = useContext(SelectionContext);
  if (value === null) {
    throw new Error("useSelection must be used within SelectionProvider");
  }
  return value;
}
