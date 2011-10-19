/*******************************************************************************/
// File name: custom_filesystem.js
// Description: Plots all the graphs for file system dashboard

//------------------ Data Loader functions--------------------------------------
// 1) fs_Bar_SpaceUsage_Data(isZoom)
// 2) fs_Line_connectedClients_Data(isZoom)
// 3) fs_LineBar_CpuMemoryUsage_Data(isZoom)
// 4) fs_Area_ReadWrite_Data(isZoom)
// 5) fs_Area_Iops_Data(isZoom)
// 6) fs_HeatMap_Data

/*****************************************************************************/
//Function for space usage for selected file systems - Pie Chart
//Param - File System name, start date, end date, datafunction (average/min/max)
//Return - Returns the graph plotted in container
/*****************************************************************************/
	fs_Bar_SpaceUsage_Data = function(fsName, sDate, endDate, dataFunction, targetKind, fetchMetrics, isZoom)
    {
		var free=0,used=0;
        var freeData = [],usedData = [],categories = [],freeFilesData = [],totalFilesData = [];
        $.post("/api/get_fs_stats_for_targets/",
        {targetkind: targetKind, datafunction: dataFunction, fetchmetrics: fetchMetrics, 
        starttime: sDate, filesystem: fsName, endtime: endDate})
	    .success(function(data, textStatus, jqXHR) 
        {   
	    	if(data.success)
		    {
		        var response = data.response;
			    var totalDiskSpace=0,totalFreeSpace=0,totalFiles=0,totalFreeFiles=0;
			    $.each(response, function(resKey, resValue) 
		        {
		    	    totalFreeSpace = resValue.kbytesfree/1024;
				    totalDiskSpace = resValue.kbytestotal/1024;
				    free = Math.round(((totalFreeSpace/1024)/(totalDiskSpace/1024))*100);
				    used = Math.round(100 - free);
				    
				    freeData.push(free);
			        usedData.push(used);
			        
			        totalFiles = resValue.filesfree/1024;
				    totalFreeFiles = resValue.filestotal/1024;
				    free = Math.round(((totalFreeSpace/1024)/(totalDiskSpace/1024))*100);
				    used = Math.round(100 - free);
				    
				    freeFilesData.push(free);
				    totalFilesData.push(used);
			        
			        categories.push(resValue.filesystem);
			    });
			    
			    
		    }
        })
	    .error(function(event) 
        {
	         // Display of appropriate error message
	    })
        .complete(function(event){
			obj_db_Bar_SpaceUsage_Data = JSON.parse(JSON.stringify(chartConfig_Bar_SpaceUsage));
			obj_db_Bar_SpaceUsage_Data.chart.renderTo = "fs_container2";
			obj_db_Bar_SpaceUsage_Data.xAxis.categories = categories;
            obj_db_Bar_SpaceUsage_Data.title.text="All File System Space Usage";
            obj_db_Bar_SpaceUsage_Data.series = [
               {data: freeData, stack: 0, name: 'Bytes'}, {data: usedData, stack: 0, name: 'Bytes'},					// first stack

		       {data: freeFilesData, stack: 1, name: 'INodes'}, {data: totalFilesData, stack: 1, name: 'INodes'}		// second stack
		    ];		
            
            if(isZoom == 'true')
	      	{
            	renderZoomDialog(obj_db_Bar_SpaceUsage_Data);
	      	}
            
            chart = new Highcharts.Chart(obj_db_Bar_SpaceUsage_Data);
        });
    }
/*****************************************************************************/
// Function for number of clients connected	- Line Chart
// Param - File System name, start date, end date, datafunction (average/min/max), targetkind , fetchematrics
// Return - Returns the graph plotted in container
/*****************************************************************************/
    fs_Line_connectedClients_Data = function(fsName, sDate, endDate, dataFunction, fetchMetrics, isZoom)
    {
    	obj_db_Line_connectedClients_Data = JSON.parse(JSON.stringify(chartConfig_Line_clientConnected));
    	var clientMountData = [], categories = [];
    	var count=0;
    	var fileSystemName = "";
          $.post("/api/get_fs_stats_for_client/",
           {datafunction: dataFunction, fetchmetrics: fetchMetrics, starttime: sDate, filesystem: fsName, endtime: endDate})
          .success(function(data, textStatus, jqXHR) 
          {   
              if(data.success)
              {
                  var response = data.response;
                  $.each(response, function(resKey, resValue) 
                  {
        	          if (fileSystemName != resValue.filesystem && fileSystemName !='')
      		          {
        	        	  obj_db_Line_connectedClients_Data.series[count] = {
      		                name: '',
      		                data: clientMountData
      		          };
      		          clientMountData = [];
      		          categories = [];
      		          count++;
      		          fileSystemName = resValue.filesystem;
      		          clientMountData.push(resValue.clients_mounts);
      		          categories.push(resValue.timestamp);
      			       }
      			       else
      			       {
      			    	fileSystemName = resValue.filesystem;
      			        clientMountData.push(resValue.clients_mounts);
      			        categories.push(resValue.timestamp);
      			       }
        	          
        	          obj_db_Line_connectedClients_Data.series[count] = { name: '', data: clientMountData };
              		   
              		  clientMountData.push(resValue.clients_mounts);
                	  categories.push(resValue.timestamp);
                  });
              }
          })
          .error(function(event) 
          {
               // Display of appropriate error message
          })
          .complete(function(event){
        	  obj_db_Line_connectedClients_Data.xAxis.categories = categories;
        	  obj_db_Line_connectedClients_Data.chart.renderTo = "fs_container3";
              obj_db_Line_connectedClients_Data.xAxis.labels = {
            		  rotation: 310,step: 4,style:{fontSize:'8px', fontWeight:'regular'}
              }
              if(isZoom == 'true')
  	      	  {
            	  renderZoomDialog(obj_db_Line_connectedClients_Data);
  	      	  }
              chart = new Highcharts.Chart(obj_db_Line_connectedClients_Data);
          });
     }

/*****************************************************************************/
// Function for cpu and memory usage - Line + Column Chart
// Param - File System name, start date, end date, datafunction (average/min/max), targetkind , fetchematrics
// Return - Returns the graph plotted in container
/*****************************************************************************/
 fs_LineBar_CpuMemoryUsage_Data = function(fsName, sDate, endDate, dataFunction, targetkind,fetchMetrics, isZoom)
 {
	    var count = 0;
        var cpuData = [],categories = [], memoryData = [];
		obj_db_LineBar_CpuMemoryUsage_Data = JSON.parse(JSON.stringify(chartConfig_LineBar_CPUMemoryUsage));
		$.post("/api/get_fs_stats_for_server/",
		  {datafunction: dataFunction, fetchmetrics: fetchMetrics, starttime: sDate, filesystem: fsName, endtime: endDate})
         .success(function(data, textStatus, jqXHR) 
          {
            var hostName='';
            var avgCPUApiResponse = data;
            if(avgCPUApiResponse.success)
            {
                 var response = avgCPUApiResponse.response;
                 $.each(response, function(resKey, resValue) 
                 {
                	cpuData.push(resValue.cpu_usage);
                	memoryData.push(resValue.mem_MemTotal - resValue.mem_MemFree);
                	
			        categories.push(resValue.timestamp);
			     });
            }
       })
       .error(function(event) {
             // Display of appropriate error message
       })
       .complete(function(event){
                obj_db_LineBar_CpuMemoryUsage_Data.xAxis.categories = categories;
                obj_db_LineBar_CpuMemoryUsage_Data.chart.renderTo = "fs_avgCPUDiv";
                
                if(isZoom == 'true')
        		{
                	renderZoomDialog(obj_db_LineBar_CpuMemoryUsage_Data);
        		}
        		
                obj_db_LineBar_CpuMemoryUsage_Data.series[0].data = cpuData;
                obj_db_LineBar_CpuMemoryUsage_Data.series[1].data = memoryData;
                
                chart = new Highcharts.Chart(obj_db_LineBar_CpuMemoryUsage_Data);
        });
    }

/*****************************************************************************/
//Function for disk read and write - Area Chart
//Param - File System name, start date, end date, datafunction (average/min/max), targetkind , fetchematrics
//Return - Returns the graph plotted in container
/*****************************************************************************/
 fs_Area_ReadWrite_Data = function(fsName, sDate, endDate, dataFunction, targetKind, fetchMetrics, isZoom)
 {
	  var count = 0;
         var readData = [],categories = [], writeData = [];
        obj_db_Area_ReadWrite_Data = JSON.parse(JSON.stringify(chartConfig_Area_ReadWrite));
        $.post("/api/get_fs_stats_for_targets/",
        	{targetkind: targetKind, datafunction: dataFunction, fetchmetrics: fetchMetrics, 
            starttime: sDate, filesystem: fsName, endtime: endDate})
         .success(function(data, textStatus, jqXHR) {
            var hostName='';
            var avgMemoryApiResponse = data;
            if(avgMemoryApiResponse.success)
             {
                 var response = avgMemoryApiResponse.response;
                 $.each(response, function(resKey, resValue)
                 {
                	readData.push(resValue.stats_read_bytes/1024);
                	writeData.push(((0-resValue.stats_write_bytes)/1024));
                 	
 			        categories.push(resValue.timestamp);
		         });
              }
       })
       .error(function(event) {
             // Display of appropriate error message
       })
       .complete(function(event){
    	   		obj_db_Area_ReadWrite_Data.chart.renderTo = "fs_avgMemoryDiv";
                obj_db_Area_ReadWrite_Data.xAxis.categories = categories;
                if(isZoom == 'true')
        		{
                	renderZoomDialog(obj_db_Area_ReadWrite_Data);
        		}
                
                obj_db_Area_ReadWrite_Data.series[0].data = readData;
                obj_db_Area_ReadWrite_Data.series[1].data = writeData;
                if(isZoom == 'true')
    	      	{
              	  renderZoomDialog(obj_db_Area_ReadWrite_Data);
    	      	}
        		chart = new Highcharts.Chart(obj_db_Area_ReadWrite_Data);
        });
}

/*****************************************************************************/
//Function for Iops - Area Chart
//Param - File System name, start date, end date, datafunction (average/min/max), targetkind , fetchematrics
//Return - Returns the graph plotted in container
/*****************************************************************************/
 fs_Area_Iops_Data = function(fsName, sDate, endDate, dataFunction, targetKind, fetchMetrics, isZoom)
 {
	    var count = 0;
        var readData = [], writeData = [], statData = [], closeData = [], openData = [], categories = [];
        obj_db_Area_Iops_Data = JSON.parse(JSON.stringify(chartConfig_Area_Iops));
        $.post("/api/get_fs_stats_for_targets/",
        	{targetkind: targetKind, datafunction: dataFunction, fetchmetrics: fetchMetrics, 
            starttime: sDate, filesystem: fsName, endtime: endDate})
         .success(function(data, textStatus, jqXHR) {
            var targetName='';
            var avgDiskReadApiResponse = data;
            if(avgDiskReadApiResponse.success)
             {
                 var response = avgDiskReadApiResponse.response;
                 $.each(response, function(resKey, resValue)
                 {
		         	  readData.push(resValue.iops1/1024);
	                  writeData.push(resValue.iops2/1024);
	                  statData.push(resValue.iops3/1024);
	                  closeData.push(resValue.iops4/1024);
	                  openData.push(resValue.iops5/1024);
	                 	
	 			      categories.push(resValue.timestamp);
		         
		         });
               }
       })
       .error(function(event) {
             // Display of appropriate error message
       })
       .complete(function(event){
    	   		obj_db_Area_Iops_Data.chart.renderTo = "fs_avgReadDiv";
                obj_db_Area_Iops_Data.xAxis.categories = categories;
                if(isZoom == 'true')
        		{
                	renderZoomDialog(obj_db_Area_Iops_Data);
        		}
                
                obj_db_Area_Iops_Data.series[0].data = readData;
                obj_db_Area_Iops_Data.series[1].data = writeData;
                obj_db_Area_Iops_Data.series[2].data = statData;
                obj_db_Area_Iops_Data.series[3].data = closeData;
                obj_db_Area_Iops_Data.series[4].data = openData;
                if(isZoom == 'true')
    	      	{
              	  renderZoomDialog(obj_db_Area_Iops_Data);
    	      	}
                chart = new Highcharts.Chart(obj_db_Area_Iops_Data);
        });
        
}
/*****************************************************************************/
//Function to plot heat map
//Return - Returns the graph plotted in container
/*****************************************************************************/
 fs_HeatMap_Data = function(isZoom)
 {
	 var obj_db_HeatMap_Data = JSON.parse(JSON.stringify(chartConfig_HeatMap));
	 obj_db_HeatMap_Data.chart.renderTo = "fs_heatMapDiv";
	 var ostName, count =0;
	 $.post("/api/get_fs_ost_heatmap/",
	          {"fetchmetrics": "cpu", "endtime": "2011-10-17 19:46:58.912171", "datafunction": "Average", 
	           "starttime": "2011-10-17 19:56:58.912150", "filesystem": ""})
	          .success(function(data, textStatus, jqXHR) 
	          {   
	              if(data.success)
	              {
	                  var response = data.response;
	                  var clientMountData = [];
	                  var valueArray = [];
	                  $.each(response, function(resKey, resValue) 
	                  {
	        	          if (ostName != resValue.ost && ostName !='')
	      		          {
	        	        	  obj_db_HeatMap_Data.series[count] = {
	      		                name: ostName,
	      		                color: 'rgba(0, 128, 0, .7)',
	      		                data: clientMountData
	        	        	  };
	      		          clientMountData = [];
	      		          categories = [];
	      		          valueArray = [];
	      		          count++;
	      		          ostName = resValue.ost;
	      		        
	      		          valueArray.push(resValue.timestamp);
	      		          valueArray.push(resValue.cpu);
	      		          
	      		          clientMountData.push(valueArray);
	      		          
	      		          categories.push(resValue.timestamp);
	      			       }
	      			       else
	      			       {
	      			    	valueArray = [];
	      			    	ostName = resValue.ost;
	      			    	
	      			    	valueArray.push(resValue.timestamp);
		      		        valueArray.push(resValue.cpu);
		      		        
		      		        clientMountData.push(valueArray);
	      			        
		      		        categories.push(resValue.timestamp);
	      			       }
	        	          
	        	          
	                  });
	              }
	              obj_db_HeatMap_Data.series[count] = { name: ostName, color: 'rgba(0, 128, 0, .7)', data: clientMountData };
         		   
          		  
	          })
	          .error(function(event) 
	          {
	               // Display of appropriate error message
	          })
	          .complete(function(event){
	        	  obj_db_HeatMap_Data.xAxis.categories = categories;
	        	  obj_db_HeatMap_Data.xAxis.labels = {
	            		  rotation: 310,step: 4,style:{fontSize:'8px', fontWeight:'regular'}
	              }
	              chart = new Highcharts.Chart(obj_db_HeatMap_Data);
	    });
	 
	  	if(isZoom == 'true')
	   	{
	   	  renderZoomDialog(obj_db_HeatMap_Data);
	   	}
	 	chart = new Highcharts.Chart(obj_db_HeatMap_Data);
      
}
/********************************************************************************/
 
 loadFileSystemSummary = function (){
	 var innerContent = "";
	 $.post("/api/getfilesystem/",{filesystem: $('#fsSelect').val()})
     .success(function(data, textStatus, jqXHR) {
         if(data.success)
         {
             var response = data.response;
             $.each(response, function(resKey, resValue) {
            	 innerContent = innerContent + "<tr><td>MGS Hostname: "+resValue.mgsname+"</td><td></td></tr>"+
                 "<tr><td width='50%'>MDS Hostname: "+resValue.mdsname+"</td><td width='50%'>Failover Status: --</td></tr>"+
                 "<tr><td>Standby MDS Hostname: --</td><td></td></tr>"+
                 "<tr><td width='50%'>Total OSSs: "+resValue.noofoss+" </td><td width='50%'>Total OSTs: "+resValue.noofost+" </td></tr>"+
                 "<tr><td>Filesystem Status: "+resValue.status+"</td><td></td></tr>"+
                 "<tr><td colspan='4' align='center'>Note: Please check Alerts/Events to detect if status is not healthy</td><td></td></tr>";
             });
         }
    })
	.error(function(event) {
	})
	.complete(function(event){
		$('#fileSystemSummaryTbl').html(innerContent);
    });
 }