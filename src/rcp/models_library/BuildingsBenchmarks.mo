within ;
package RCPBenchmarks
  "Stable RCP wrappers around the pinned LBNL Buildings data-center examples"

  partial model ChillerCooledOutputs
    output Real T_room_K(unit="K") "Computer-room return-air temperature";
    output Real P_HVAC_W(unit="W") "HVAC electric power";
    output Real P_IT_W(unit="W") "IT electric power";
    output Real E_HVAC_J(unit="J") "Cumulative HVAC electric energy";
    output Real E_IT_J(unit="J") "Cumulative IT electric energy";
    output Real free_cooling_s(unit="s") "Time in free-cooling mode";
    output Real partial_mechanical_s(unit="s") "Time in partial-mechanical mode";
    output Real full_mechanical_s(unit="s") "Time in full-mechanical mode";
    output Integer mode_switches "Cooling-mode switch count";
  end ChillerCooledOutputs;

  model ChillerCooledIntegrated
    "Integrated primary-secondary waterside-economizer benchmark"
    parameter Modelica.Units.SI.Power Q_room=500000 "Computer-room heat load";
    parameter Modelica.Units.SI.Temperature T_chw_set=281.15
      "Chilled-water supply setpoint";
    extends Buildings.Applications.DataCenters.ChillerCooled.Examples.IntegratedPrimarySecondaryEconomizer(
      TCHWSet=T_chw_set,
      roo(QRoo_flow=Q_room),
      weaData(filNam="/opt/modelica/Buildings/Resources/weatherdata/DRYCOLD.mos"));
    extends ChillerCooledOutputs;
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
  end ChillerCooledIntegrated;

  model ChillerCooledNonIntegrated
    "Non-integrated primary-secondary waterside-economizer benchmark"
    parameter Modelica.Units.SI.Power Q_room=500000 "Computer-room heat load";
    parameter Modelica.Units.SI.Temperature T_chw_set=281.15
      "Chilled-water supply setpoint";
    extends Buildings.Applications.DataCenters.ChillerCooled.Examples.NonIntegratedPrimarySecondaryEconomizer(
      TCHWSet=T_chw_set,
      roo(QRoo_flow=Q_room),
      weaData(filNam="/opt/modelica/Buildings/Resources/weatherdata/DRYCOLD.mos"));
    extends ChillerCooledOutputs;
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
  end ChillerCooledNonIntegrated;
end RCPBenchmarks;
