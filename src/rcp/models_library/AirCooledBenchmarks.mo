within ;
package RCPAirCooled
  "Stable RCP wrappers around the pinned LBNL Buildings air-cooled data-center examples"

  partial model DXCooledOutputs
    output Real T_room_K(unit="K") "Computer-room air temperature";
    output Real P_HVAC_W(unit="W") "HVAC electric power (DX compressor and supply fan)";
    output Real P_IT_W(unit="W") "IT electric power";
    output Real E_HVAC_J(unit="J") "Cumulative HVAC electric energy";
    output Real E_IT_J(unit="J") "Cumulative IT electric energy";
    output Real free_cooling_s(unit="s") "Time in free-cooling mode";
    output Real partial_mechanical_s(unit="s") "Time in partial-mechanical mode";
    output Real full_mechanical_s(unit="s") "Time in full-mechanical mode";
    output Integer mode_switches "Cooling-mode switch count";
  end DXCooledOutputs;

  model DXCooledAirsideEconomizer
    "Air-cooled DX benchmark with airside economizer"
    parameter Modelica.Units.SI.HeatFlowRate Q_room=500000 "Computer-room heat load";
    parameter Modelica.Units.SI.Temperature T_room_set=298.15 "Room air setpoint";
    parameter Modelica.Units.SI.Temperature T_sup_set=291.13 "Supply-air setpoint";
    extends Buildings.Applications.DataCenters.DXCooled.Examples.DXCooledAirsideEconomizer(
      QRooInt_flow=Q_room,
      TRooSet=T_room_set,
      TAirSupSet=T_sup_set,
      weaDat(filNam="/opt/modelica/Buildings/Resources/weatherdata/USA_IL_Chicago-OHare.Intl.AP.725300_TMY3.mos"));
    extends DXCooledOutputs;
  equation
    T_room_K = roo.TRooAir;
    P_HVAC_W = PHVAC.y;
    P_IT_W = PIT.y;
    E_HVAC_J = EHVAC.y;
    E_IT_J = EIT.y;
    free_cooling_s = FCTim.y;
    partial_mechanical_s = PMCTim.y;
    full_mechanical_s = FMCHou.y;
    mode_switches = swiTim.y;
  end DXCooledAirsideEconomizer;
end RCPAirCooled;
